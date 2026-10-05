"""Hazard Event Service (M02).

Business logic for the hazard-event layer. Every source (IoT, citizen report,
authority, system) goes through here and produces/updates an Incident.
Lifecycle state changes are handed to notification_service (M03); this module
never builds notifications itself.
"""

import math
from datetime import datetime, timedelta

from sqlalchemy.orm.attributes import set_committed_value

from app.extensions import db
from app.models import Incident, IncidentAffectedDistrict, IncidentStatusHistory, River, RoadSegment, District
from app.services import emergency_dispatcher, notification_service
from app.models.incident import (
    HAZARD_TYPES, HAZARD_SOURCES, HAZARD_SEVERITY, HAZARD_STATUS,
    ACTIVE_STATUSES, VALID_STATUS_TRANSITIONS,
)

# An active event with evidence newer than this is "the same hazard" for
# district/location matches. River/road matches ignore the window.
DEDUP_WINDOW_HOURS = 24
DEDUP_DISTANCE_KM = 5.0

# risk_engine risk_level (0 unknown, 1 normal, 2 rising, 3 flooding) -> severity
RISK_LEVEL_SEVERITY = {2: 'medium', 3: 'high'}

# A citizen report is unverified evidence: it opens/joins an event at 'medium'
# and can never escalate it. Severity changes come from authorities (or M06 later).
CITIZEN_REPORT_SEVERITY = 'medium'


def _validate_hazard_type(event_type):
    if event_type not in HAZARD_TYPES:
        raise ValueError(f"Invalid hazard type: {event_type}. Must be one of {HAZARD_TYPES}")


def _validate_severity(severity):
    if severity not in HAZARD_SEVERITY:
        raise ValueError(f"Invalid severity: {severity}. Must be one of {HAZARD_SEVERITY}")


def _validate_source(source):
    if source not in HAZARD_SOURCES:
        raise ValueError(f"Invalid source: {source}. Must be one of {HAZARD_SOURCES}")


def _validate_status(status):
    if status not in HAZARD_STATUS:
        raise ValueError(f"Invalid status: {status}. Must be one of {HAZARD_STATUS}")


def _validate_coordinates(latitude, longitude):
    if (latitude is None) != (longitude is None):
        raise ValueError("Latitude and longitude must be provided together")
    if latitude is None:
        return
    for name, value in (('Latitude', latitude), ('Longitude', longitude)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a number")
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180")


def _validate_confidence(confidence):
    if confidence is None:
        return
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        raise ValueError("Confidence must be a number between 0.0 and 1.0")


def _bounding_box(latitude, longitude, radius_km):
    lat_delta = radius_km / 111.0
    # a degree of longitude shrinks with cos(latitude)
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(latitude)), 0.01))
    return (Incident.latitude.between(latitude - lat_delta, latitude + lat_delta),
            Incident.longitude.between(longitude - lon_delta, longitude + lon_delta))


def create_hazard_event(event_type, severity, source, district_id=None, location=None,
                        latitude=None, longitude=None, river_id=None, road_segment_id=None,
                        title=None, description=None, source_reference=None,
                        confidence=None, detected_at=None, notify_exclude_user_ids=(), before_commit=None):
    """Validate and create a new hazard event in 'detected' status. Raises ValueError.

    notify_exclude_user_ids: users not to send the 'detected' alert to (e.g. the
    citizen whose report created it — they get a report receipt instead).
    before_commit(incident): caller's writes that must commit atomically with the new event
    (Phase 4A: the seismic Device Event -> Incident association).
    """
    _validate_hazard_type(event_type)
    _validate_severity(severity)
    _validate_source(source)
    _validate_coordinates(latitude, longitude)
    _validate_confidence(confidence)

    if district_id and not db.session.get(District, district_id):
        raise ValueError(f"Invalid district_id: {district_id}")
    river = db.session.get(River, river_id) if river_id else None
    if river_id and not river:
        raise ValueError(f"Invalid river_id: {river_id}")
    road = db.session.get(RoadSegment, road_segment_id) if road_segment_id else None
    if road_segment_id and not road:
        raise ValueError(f"Invalid road_segment_id: {road_segment_id}")
    for linked in (river, road):
        if linked and district_id and linked.district_id and linked.district_id != district_id:
            raise ValueError("River/road segment does not belong to the given district")

    now = datetime.utcnow()
    incident = Incident(
        event_type=event_type,
        severity=severity,
        source=source,
        district_id=district_id,
        location=location,
        latitude=latitude,
        longitude=longitude,
        river_id=river_id,
        road_segment_id=road_segment_id,
        title=title,
        description=description,
        source_reference=source_reference,
        status='detected',
        confidence=confidence,
        report_count=1,
        detected_at=detected_at or now,
        updated_at=now,
    )
    db.session.add(incident)
    db.session.flush()  # need incident.id for the notification link
    notification_service.notify_hazard_detected(incident, notify_exclude_user_ids)
    if before_commit:
        before_commit(incident)
    _commit_or_rollback()
    return incident


def find_active_related_event(event_type, district_id=None, river_id=None, road_segment_id=None,
                              latitude=None, longitude=None, hours=None):
    """Return the active event that new evidence belongs to, or None.

    - same river / road segment: one active event per (type, river|road), no time window
    - otherwise: same district and/or within DEDUP_DISTANCE_KM, with evidence in the last `hours`
    """
    query = Incident.query.filter(
        Incident.event_type == event_type,
        Incident.status.in_(ACTIVE_STATUSES),
    )

    if river_id:
        query = query.filter(Incident.river_id == river_id)
    elif road_segment_id:
        query = query.filter(Incident.road_segment_id == road_segment_id)
    else:
        if district_id is None and latitude is None:
            return None  # nothing to match on
        since = datetime.utcnow() - timedelta(hours=hours or DEDUP_WINDOW_HOURS)
        query = query.filter(db.func.coalesce(Incident.updated_at, Incident.detected_at) >= since)
        if district_id:
            query = query.filter(Incident.district_id == district_id)
        if latitude is not None and longitude is not None:
            query = query.filter(*_bounding_box(latitude, longitude, DEDUP_DISTANCE_KM))

    return query.order_by(Incident.detected_at.desc()).first()


def add_evidence(incident, severity=None, source_reference=None):
    """Attach a new piece of evidence to an existing active event.

    Bumps report_count and escalates severity (never lowers it automatically;
    lowering is an authority decision). Does not change lifecycle status.
    """
    incident.report_count = (incident.report_count or 0) + 1
    previous = incident.severity
    if severity and HAZARD_SEVERITY.index(severity) > HAZARD_SEVERITY.index(previous or 'low'):
        incident.severity = severity
        notification_service.notify_hazard_escalated(incident, previous)
    if source_reference:
        incident.source_reference = source_reference
    incident.updated_at = datetime.utcnow()
    _commit_or_rollback()
    return incident


def report_hazard(event_type, severity, source, escalate=True, **fields):
    """Create a new event, or merge into the matching active one. Returns (incident, created).

    escalate=False: merged evidence never raises the existing event's severity
    (used for unverified citizen photo reports).
    source='citizen_report' always uses CITIZEN_REPORT_SEVERITY and never escalates,
    whatever the caller passes (M05.1).
    """
    if source == 'citizen_report':
        severity, escalate = CITIZEN_REPORT_SEVERITY, False
    _validate_hazard_type(event_type)
    _validate_severity(severity)
    _validate_coordinates(fields.get('latitude'), fields.get('longitude'))
    existing = find_active_related_event(
        event_type,
        district_id=fields.get('district_id'),
        river_id=fields.get('river_id'),
        road_segment_id=fields.get('road_segment_id'),
        latitude=fields.get('latitude'),
        longitude=fields.get('longitude'),
    )
    if existing:
        return add_evidence(existing, severity if escalate else None, fields.get('source_reference')), False
    return create_hazard_event(event_type, severity, source, **fields), True


_STATUS_NOTIFIERS = {
    'confirmed': notification_service.notify_hazard_confirmed,
    'resolved': notification_service.notify_hazard_resolved,
}


class TransitionConflict(ValueError):
    """The incident's status changed underneath this request (another user got there first)."""


def _apply_transition(incident, new_status, actor_id=None, note=None):
    """The single path for status changes, so notifications and the audit trail can't be bypassed.

    Compare-and-set: the UPDATE only matches if the row still has the status we validated
    against, so two concurrent identical requests can't both succeed or both write history.
    The history row is added in the same transaction as the status change. Does not commit.
    """
    _validate_status(new_status)
    old_status = incident.status
    if not incident.can_transition_to(new_status):
        raise ValueError(f"Invalid transition from {old_status} to {new_status}")
    now = datetime.utcnow()
    values = {'status': new_status, 'updated_at': now}
    if new_status == 'resolved':
        values['resolved_at'] = now
    db.session.flush()
    changed = Incident.query.filter(Incident.id == incident.id, Incident.status == old_status) \
        .update(values, synchronize_session=False)
    if changed != 1:
        raise TransitionConflict('Hazard status was changed by someone else; reload and try again')
    for key, value in values.items():  # keep the in-memory object in step with the row
        set_committed_value(incident, key, value)
    db.session.add(IncidentStatusHistory(incident_id=incident.id, previous_status=old_status,
                                         new_status=new_status, changed_by_id=actor_id, note=note))
    notifier = _STATUS_NOTIFIERS.get(new_status)
    if notifier:
        notifier(incident)
    return old_status


def _commit_or_rollback():
    """Commit, then deliver the Web Push queued by the notifications in it (M12, best-effort)."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        emergency_dispatcher.discard()
        raise
    emergency_dispatcher.flush()


def transition_event_status(incident, new_status, actor_id=None, note=None):
    """Validated lifecycle transition + audit row, atomically. Returns old status. Raises ValueError
    (TransitionConflict if another request changed the status first). Rolls back on any failure."""
    try:
        old_status = _apply_transition(incident, new_status, actor_id, note)
    except Exception:
        db.session.rollback()
        emergency_dispatcher.discard()
        raise
    _commit_or_rollback()
    return old_status


def update_event(incident, severity=None, status=None, actor_id=None, note=None, **fields):
    """Authority/admin edit. Validates everything before changing anything.

    Raising severity notifies an escalation; lowering it is allowed (a human
    decision) and is silent. `fields` must already be validated by the caller
    (title, description, location, latitude, longitude).
    """
    if severity is not None:
        _validate_severity(severity)
    if status is not None:
        _validate_status(status)
        if not incident.can_transition_to(status):
            raise ValueError(f"Invalid transition from {incident.status} to {status}")

    for key, value in fields.items():
        setattr(incident, key, value)
    if severity is not None and severity != incident.severity:
        previous = incident.severity
        incident.severity = severity
        notification_service.notify_hazard_escalated(incident, previous)
    if status is not None:
        _apply_transition(incident, status, actor_id, note)
    incident.updated_at = datetime.utcnow()
    _commit_or_rollback()
    return incident


def add_affected_district(incident, district_id):
    """Add an extra affected district (M04). Raises ValueError / LookupError.

    The primary district (incident.district_id) is always affected implicitly and
    can't be added again. Newly covered users are notified of the current state
    once; users already notified get nothing. Resolved/rejected events keep the
    area for history but send no alerts.
    """
    if not db.session.get(District, district_id):
        raise LookupError(f"District {district_id} not found")
    if district_id in incident.affected_district_ids:
        raise ValueError("District is already affected by this hazard")
    db.session.add(IncidentAffectedDistrict(incident_id=incident.id, district_id=district_id))
    db.session.flush()
    db.session.expire(incident, ['additional_districts'])
    sent = notification_service.notify_area_expanded(incident)
    _commit_or_rollback()
    return sent


def remove_affected_district(incident, district_id):
    """Stop targeting an extra district. History (notifications, lifecycle) is untouched."""
    if district_id == incident.district_id:
        raise ValueError("The primary district can't be removed")
    row = IncidentAffectedDistrict.query.filter_by(incident_id=incident.id, district_id=district_id).first()
    if not row:
        raise LookupError("District is not an additional affected district of this hazard")
    db.session.delete(row)
    db.session.commit()
    db.session.expire(incident, ['additional_districts'])


# M09: resolution/rejection notes are internal and live in the status history; they are no
# longer appended to Incident.description, which is public (/api/hazards, M07 dashboard).
def resolve_event(incident, resolution_notes=None, actor_id=None):
    transition_event_status(incident, 'resolved', actor_id, resolution_notes)
    return incident


def reject_event(incident, reason=None, actor_id=None):
    transition_event_status(incident, 'rejected', actor_id, reason)
    return incident


def escalate_to_investigating(incident):
    transition_event_status(incident, 'investigating')
    return incident


def confirm_event(incident):
    transition_event_status(incident, 'confirmed')
    return incident


def update_event_from_iot(incident, risk_assessment, source_reference=None):
    """Apply a repeated rising/flooding reading to an existing flood event."""
    if incident.event_type != 'flood':
        return False
    add_evidence(incident, RISK_LEVEL_SEVERITY.get(risk_assessment['risk_level']), source_reference)
    return True


def auto_create_flood_event_from_river(river, risk_assessment, device=None):
    """Bridge from the deterministic M01 risk engine to the event layer.

    Only rising/flooding assessments produce evidence; normal/unknown returns None.
    risk_engine stays authoritative for the threshold decision.
    """
    if risk_assessment['status'] not in ('rising', 'flooding') or not risk_assessment.get('alert_required', True):
        return None

    source_ref = f'device_{device.id}' if device else f'river_{river.id}'
    existing = find_active_related_event('flood', river_id=river.id)
    if existing:
        update_event_from_iot(existing, risk_assessment, source_ref)
        return existing

    district = db.session.get(District, river.district_id) if river.district_id else None
    district_name = district.name if district else None
    percentage = risk_assessment.get('percentage')
    has_coords = device is not None and device.latitude is not None and device.longitude is not None

    return create_hazard_event(
        event_type='flood',
        severity=RISK_LEVEL_SEVERITY[risk_assessment['risk_level']],
        source='iot',
        district_id=river.district_id,
        location=district_name,
        latitude=device.latitude if has_coords else None,
        longitude=device.longitude if has_coords else None,
        river_id=river.id,
        title=f"{risk_assessment['status'].title()} detected: {river.name}",
        description=(
            f"{river.name} in {district_name or 'unknown district'} is {risk_assessment['status']} "
            f"at {river.current_level}m"
            + (f" ({percentage:.0f}% of danger level)" if percentage is not None else "")
            + f". {risk_assessment.get('reason', '')}"
        ).strip(),
        source_reference=source_ref,
        confidence=None,  # deterministic threshold, not a probabilistic model
    )


def affects_district(district_id):
    """SQL filter: incident's primary district OR an additional affected district (M04)."""
    additional = db.session.query(IncidentAffectedDistrict.incident_id)         .filter(IncidentAffectedDistrict.district_id == district_id)
    return db.or_(Incident.district_id == district_id, Incident.id.in_(additional))


def get_active_events_for_district(district_id):
    return Incident.query.filter(
        affects_district(district_id),
        Incident.status.in_(ACTIVE_STATUSES),
    ).order_by(Incident.detected_at.desc()).all()


def get_events_by_type(event_type, status=None, limit=100):
    query = Incident.query.filter_by(event_type=event_type)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Incident.detected_at.desc()).limit(limit).all()


def get_events_by_source(source, limit=100):
    return Incident.query.filter_by(source=source).order_by(Incident.detected_at.desc()).limit(limit).all()


def get_events_near_location(latitude, longitude, radius_km=10, limit=50):
    return Incident.query.filter(*_bounding_box(latitude, longitude, radius_km)) \
        .order_by(Incident.detected_at.desc()).limit(limit).all()


def get_event_statistics():
    def counts(column, keys):
        rows = dict(db.session.query(column, db.func.count(Incident.id)).group_by(column).all())
        return {k: rows.get(k, 0) for k in keys}

    return {
        'total': Incident.query.count(),
        'by_status': counts(Incident.status, HAZARD_STATUS),
        'by_type': counts(Incident.event_type, HAZARD_TYPES),
        'by_source': counts(Incident.source, HAZARD_SOURCES),
        'by_severity': counts(Incident.severity, HAZARD_SEVERITY),
    }
