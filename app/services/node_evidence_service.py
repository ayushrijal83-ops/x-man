"""Camera-node field evidence (M-LIVE-02): the server side of the future Android field node.

    authenticated camera_node device (iot.authenticate_device, kind == 'camera_node')
      -> metadata allow-list (server-owned fields refused) + frames via citizen_report_service.process_image
      -> idempotency on (device, client_event_id)
      -> device row locked, per-device hourly limit, NodeEvidence row
      -> capture-time / GPS plausibility, hold policy
      -> hazard_event_service.report_hazard('landslide', 'medium', 'iot', escalate=False,
                                            district = device's provisioned district)   (M02 dedup, M03/M04/M12 alerts)
      -> after commit: server-side vision corroboration on the last frame (ai_* fields only)

Everything authoritative is derived here from server state: hazard type, severity, source, status,
district, trusted coordinates. Client values (device_score, GPS, clocks) are stored as evidence only.
"""
import json
import math
import os
import re
import uuid
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import IoTDevice, NodeEvidence
from app.models.incident_response import IncidentStatusHistory
from app.models.node_evidence import EVIDENCE_REVIEW_STATUS, MAX_FRAMES
from app.services import citizen_report_service
from app.services.citizen_report_service import ReportError, process_image
from app.services.hazard_event_service import find_active_related_event, report_hazard

HAZARD_TYPE = 'landslide'
SEVERITY = 'medium'  # fixed: a node's own score never sets or raises severity
SOURCE = 'iot'
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_METADATA_CHARS = 4096
CLIENT_EVENT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
FRAME_FIELDS = tuple(f'frame_{i}' for i in range(MAX_FRAMES))
_STORED_NAME = citizen_report_service._STORED_NAME  # same '<uuid4 hex>.jpg' convention as reports

# metadata keys the phone may send; everything else is refused
TEXT_FIELDS = {'model': 100, 'model_version': 64, 'app_version': 32, 'network_type': 20}
ALLOWED_FIELDS = {'client_event_id', 'captured_at', 'latitude', 'longitude', 'gps_accuracy_m', 'gps_fix_at',
                  'device_score', 'battery_pct', *TEXT_FIELDS}
# server-owned state: named explicitly in the error so a client bug is obvious
FORBIDDEN_FIELDS = {'severity', 'district', 'district_id', 'status', 'confirmed', 'authority', 'authority_id',
                    'recipients', 'incident_id', 'event_type', 'hazard_type', 'source', 'received_at',
                    'affected_districts', 'device_id', 'review_status'}


class EvidenceError(ReportError):
    """Validation failure; `status` is the HTTP status to return."""


def upload_dir():
    return current_app.config.get('EVIDENCE_UPLOAD_DIR') or \
        os.path.join(current_app.instance_path, 'uploads', 'evidence')


def frame_path(evidence, index):
    """Absolute path of one stored frame, or None (bad index, or a stored name that is not ours)."""
    frames = evidence.frames
    if not 0 <= index < len(frames) or not _STORED_NAME.match(frames[index]):
        return None
    return os.path.join(upload_dir(), frames[index])


# --- validation ---------------------------------------------------------------

def _number(data, key, low, high):
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise EvidenceError(f'{key} must be a number between {low} and {high}')
    return float(value)


def _timestamp(data, key, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise EvidenceError(f'{key} is required')
        return None
    from app.routes.iot import _Invalid, _parse_timestamp  # the telemetry parser: ISO 8601 -> naive UTC
    try:
        return _parse_timestamp(value)
    except _Invalid:
        raise EvidenceError(f'{key} must be an ISO 8601 timestamp')


def parse_metadata(raw):
    """The `metadata` multipart field -> validated dict. Raises EvidenceError (400)."""
    if not isinstance(raw, str) or not raw.strip():
        raise EvidenceError('metadata (JSON object) is required')
    if len(raw) > MAX_METADATA_CHARS:
        raise EvidenceError('metadata is too large')
    try:
        data = json.loads(raw)
    except ValueError:
        raise EvidenceError('metadata must be valid JSON')
    if not isinstance(data, dict):
        raise EvidenceError('metadata must be a JSON object')

    forbidden = sorted(set(data) & FORBIDDEN_FIELDS)
    if forbidden:
        raise EvidenceError(f"Server-owned field(s) not allowed: {', '.join(forbidden)}")
    unknown = sorted(set(data) - ALLOWED_FIELDS)
    if unknown:
        raise EvidenceError(f"Unknown field(s): {', '.join(unknown)}")

    client_event_id = data.get('client_event_id')
    if not isinstance(client_event_id, str) or not CLIENT_EVENT_ID_RE.match(client_event_id):
        raise EvidenceError('client_event_id is required: 8-64 characters, letters, digits, "_" or "-"')

    from app.routes.iot import _Invalid, _coords
    try:
        latitude, longitude = _coords(data)
    except _Invalid as e:
        raise EvidenceError(str(e))

    texts = {}
    for key, limit in TEXT_FIELDS.items():
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
            raise EvidenceError(f'{key} must be a printable string of at most {limit} characters')
        texts[key] = value.strip()

    return {
        'client_event_id': client_event_id,
        'captured_at': _timestamp(data, 'captured_at', required=True),
        'gps_fix_at': _timestamp(data, 'gps_fix_at'),
        'latitude': latitude, 'longitude': longitude,
        'gps_accuracy_m': _number(data, 'gps_accuracy_m', 0, 100_000),
        'device_score': _number(data, 'device_score', 0, 1),
        'battery_pct': _number(data, 'battery_pct', 0, 100),
        **texts,
    }


def read_frames(files):
    """request.files -> sanitized JPEG bytes in frame order. Only frame_0..frame_2, at most one each,
    frame_0 required, no gaps. Each frame goes through the M05 sanitizer (re-encoded, EXIF dropped)."""
    unknown = sorted(set(files.keys()) - set(FRAME_FIELDS))
    if unknown:
        raise EvidenceError(f'Unknown file field(s): {", ".join(unknown)} (at most {MAX_FRAMES} frames: '
                            f'{", ".join(FRAME_FIELDS)})')
    present = [name for name in FRAME_FIELDS if name in files]
    if not present:
        raise EvidenceError('At least one frame (frame_0) is required')
    if present != list(FRAME_FIELDS[:len(present)]):
        raise EvidenceError('Frames must be frame_0, frame_1, frame_2 in order, without gaps')
    frames = []
    for name in present:
        uploads = files.getlist(name)
        if len(uploads) != 1:
            raise EvidenceError(f'{name} was sent more than once')
        try:
            frames.append(process_image(uploads[0]))
        except ReportError as e:
            raise EvidenceError(f'{name}: {e}', e.status)
    return frames


# --- plausibility -------------------------------------------------------------

def _distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, a)))


def check_gps(device, meta, config):
    """(gps_status, location_source, (lat, lon) for the Incident or (None, None)).

    The phone's fix is trusted only when it is present, accurate, fresh relative to the capture and
    within NODE_MAX_DISTANCE_KM of the node's registered location. Otherwise the registered location
    is used. A node without registered coordinates has no reference, so its GPS is recorded but never
    used: the Incident is district-level only. The district itself never comes from GPS."""
    registered = (device.latitude, device.longitude) if device.latitude is not None else None
    fallback = ('registered', registered) if registered else ('district', (None, None))
    lat, lon, accuracy, fix_at = meta['latitude'], meta['longitude'], meta['gps_accuracy_m'], meta['gps_fix_at']
    if lat is None:
        status = 'missing'
    elif accuracy is None or accuracy > config['NODE_MAX_GPS_ACCURACY_M']:
        status = 'inaccurate'
    elif fix_at is not None and abs((meta['captured_at'] - fix_at).total_seconds()) \
            > config['NODE_MAX_GPS_FIX_AGE_SECONDS']:
        status = 'stale_fix'
    elif registered is None:
        status = 'no_reference'
    elif _distance_km(lat, lon, *registered) > config['NODE_MAX_DISTANCE_KM']:
        status = 'outside_radius'
    else:
        return 'accepted', 'gps', (lat, lon)
    return (status, *fallback)


def hold_reason(device, meta, now, config, related_active):
    """Why this evidence must not open a new Incident, or None.

    - capture time in the future (> 5 min) or older than NODE_MAX_EVIDENCE_AGE_HOURS: the clock or the
      upload is not trustworthy for a live event -> always held
    - the node's own evidence led to an Incident that was rejected within
      NODE_HOLD_AFTER_REJECTION_HOURS -> held, unless an active related landslide already exists
      (attaching to it opens nothing new). After the window, normal processing resumes."""
    if meta['captured_at'] - now > MAX_FUTURE_SKEW:
        return 'future_capture'
    if now - meta['captured_at'] > timedelta(hours=config['NODE_MAX_EVIDENCE_AGE_HOURS']):
        return 'stale_capture'
    if related_active is None:
        since = now - timedelta(hours=config['NODE_HOLD_AFTER_REJECTION_HOURS'])
        rejected = db.session.query(IncidentStatusHistory.id) \
            .join(NodeEvidence, NodeEvidence.incident_id == IncidentStatusHistory.incident_id) \
            .filter(NodeEvidence.device_id == device.id, IncidentStatusHistory.new_status == 'rejected',
                    IncidentStatusHistory.created_at >= since).first()
        if rejected:
            return 'after_rejection'
    return None


# --- submission ---------------------------------------------------------------

class RateLimited(Exception):
    pass


def existing(device, client_event_id):
    return NodeEvidence.query.filter_by(device_id=device.id, client_event_id=client_event_id).first()


def submit(device, metadata_raw, files):
    """Validate and store one evidence package. Returns (evidence, created).

    created=False: this (device, client_event_id) was already stored; nothing new is written, no
    Incident or notification is created. Raises EvidenceError / RateLimited."""
    meta = parse_metadata(metadata_raw)
    duplicate = existing(device, meta['client_event_id'])
    if duplicate:  # retries of a stored event always succeed, even over the rate limit
        return duplicate, False
    frames = read_frames(files)  # CPU work before any lock is taken
    config = current_app.config
    now = datetime.utcnow()

    # Lock the device row first: SQLite takes its write lock here and PostgreSQL a row lock, so
    # concurrent uploads of this device are serialized from here to the commit. The duplicate and
    # rate-limit checks below therefore can't both pass for two concurrent requests.
    IoTDevice.query.filter_by(id=device.id).update({'last_seen': now}, synchronize_session=False)
    duplicate = existing(device, meta['client_event_id'])
    if duplicate:
        db.session.rollback()
        return duplicate, False
    recent = NodeEvidence.query.filter(NodeEvidence.device_id == device.id,
                                       NodeEvidence.received_at >= now - timedelta(hours=1)).count()
    if recent >= config['NODE_MAX_EVIDENCE_PER_HOUR']:
        db.session.rollback()
        raise RateLimited()

    gps_status, location_source, (lat, lon) = check_gps(device, meta, config)
    related = find_active_related_event(HAZARD_TYPE, district_id=device.district_id, latitude=lat, longitude=lon)
    reason = hold_reason(device, meta, now, config, related)

    directory = upload_dir()
    os.makedirs(directory, exist_ok=True)
    names = [f'{uuid.uuid4().hex}.jpg' for _ in frames]
    paths = [os.path.join(directory, name) for name in names]
    try:
        for path, jpeg in zip(paths, frames):
            with open(path, 'xb') as f:  # 'x': never overwrite
                f.write(jpeg)
        evidence = NodeEvidence(
            device_id=device.id, client_event_id=meta['client_event_id'], district_id=device.district_id,
            captured_at=meta['captured_at'], gps_fix_at=meta['gps_fix_at'], received_at=now,
            latitude=meta['latitude'], longitude=meta['longitude'], gps_accuracy_m=meta['gps_accuracy_m'],
            gps_status=gps_status, location_source=location_source,
            device_score=meta['device_score'], device_model=meta.get('model'),
            device_model_version=meta.get('model_version'), app_version=meta.get('app_version'),
            battery_pct=meta['battery_pct'], network_type=meta.get('network_type'),
            frame_filenames=','.join(names), status='held' if reason else 'received', hold_reason=reason)
        db.session.add(evidence)
        db.session.flush()
        if reason:
            db.session.commit()
        else:
            # report_hazard commits this transaction (evidence + incident + notifications together);
            # it creates a new event or merges into the matching active one (M02 dedup), never escalates
            incident, _ = report_hazard(
                HAZARD_TYPE, SEVERITY, SOURCE, escalate=False,
                district_id=device.district_id, latitude=lat, longitude=lon,
                location=device.location_description or device.name,
                title=f'Possible active landslide: camera node {device.name}',
                source_reference=f'evidence_{evidence.id}',
                # the event is when the node observed it (accepted capture time, within the plausible window)
                detected_at=meta['captured_at'],
            )
            evidence.incident_id, evidence.status = incident.id, 'attached'
            db.session.commit()
    except Exception:
        db.session.rollback()
        for path in paths:
            if os.path.exists(path):
                os.remove(path)
        raise
    analyze(evidence)
    return evidence, True


def analyze(evidence):
    """Server-side vision corroboration on the last (post-event) frame. Best-effort: the evidence and
    its Incident are already committed, so no failure here may surface as an error."""
    try:
        citizen_report_service.record_vision_analysis(
            evidence, frame_path(evidence, len(evidence.frames) - 1), f'evidence {evidence.id}')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Vision analysis crashed for evidence %s: %s', evidence.id, type(e).__name__)


# --- visibility / review --------------------------------------------------------

def can_view(user, evidence):
    """Admins, or an authority responsible for the evidence's (device's) district. Never citizens."""
    if user.role == 'admin':
        return True
    return user.role == 'authority' and user.authority is not None \
        and user.authority.district_id == evidence.district_id


def visible_query(user):
    if user.role == 'admin':
        return NodeEvidence.query
    if user.role == 'authority' and user.authority is not None:
        return NodeEvidence.query.filter(NodeEvidence.district_id == user.authority.district_id)
    return NodeEvidence.query.filter(db.false())


def review(reviewer, evidence, status):
    """Accept/reject the evidence item only; the Incident lifecycle stays with /api/hazards."""
    if status not in EVIDENCE_REVIEW_STATUS[1:]:
        raise EvidenceError(f'status must be one of {EVIDENCE_REVIEW_STATUS[1:]}')
    if evidence.review_status != 'submitted':
        raise EvidenceError(f'Evidence was already {evidence.review_status}', status=409)
    evidence.review_status, evidence.reviewed_by_id, evidence.reviewed_at = status, reviewer.id, datetime.utcnow()
    db.session.commit()
    return evidence


def to_dict(evidence):
    """For authorized reviewers only. No filenames or paths: frames are served by id + index."""
    return {
        'id': evidence.id, 'device': evidence.device.device_id if evidence.device else None,
        'district': evidence.district.name if evidence.district else None,
        'incident_id': evidence.incident_id, 'status': evidence.status, 'hold_reason': evidence.hold_reason,
        'captured_at': evidence.captured_at.isoformat() if evidence.captured_at else None,
        'received_at': evidence.received_at.isoformat() if evidence.received_at else None,
        'gps_status': evidence.gps_status, 'location_source': evidence.location_source,
        'frames': [f'/api/iot/evidence/{evidence.id}/frames/{i}' for i in range(len(evidence.frames))],
        'review_status': evidence.review_status,
        'ai': {'status': evidence.ai_status, 'label': evidence.ai_label, 'confidence': evidence.ai_confidence},
    }
