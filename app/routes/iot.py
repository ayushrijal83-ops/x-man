"""IoT API blueprint for hardware device telemetry ingestion."""
from flask import Blueprint, jsonify, request, g, send_file
from flask_login import current_user
from werkzeug.exceptions import RequestEntityTooLarge
from app.extensions import RUNTIME, csrf, db
from app.models import IoTDevice, NodeEvidence, SensorReading, District, Authority, River
from app.services.risk_engine import validate_sensor_reading, compute_river_status
from app.services import node_evidence_service as evidence_service, risk_service
from app.services.seismic_state_persistence import restore_state_machine
from datetime import datetime, timezone
import json
import math
import re

iot_bp = Blueprint('iot', __name__, url_prefix='/api/iot')

# ':' is the Bearer separator (device_id:api_key), so it can't be part of a device id.
DEVICE_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
DEVICE_STATUSES = ['active', 'inactive', 'maintenance', 'decommissioned']
DEVICE_TEXT_LIMITS = {'name': 100, 'description': 1000, 'location_description': 200, 'firmware_version': 50}
CAMERA_NODE_SENSOR_TYPES = ('battery',)  # node health only
DEVICE_UPDATE_FIELDS = {'enabled', 'status', 'firmware_version', 'location_description', 'latitude', 'longitude',
                        'river_id'}


class _Invalid(ValueError):
    pass


def _manager_error():
    """None if the caller is an admin or a *linked* authority, else a JSON error response (M10)."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401
    if current_user.role not in ('authority', 'admin'):
        return jsonify({'error': 'Authority or admin role required'}), 403
    if current_user.role == 'authority' and not current_user.authority_id:
        # an unlinked authority must never fall through to an unscoped query
        return jsonify({'error': 'Authority user not linked to an authority'}), 403
    return None


def _can_manage_device(device):
    return current_user.role == 'admin' or (
        current_user.authority_id is not None and device.authority_id == current_user.authority_id)


def _strict_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Invalid(f'{name} must be an integer')
    return value


def _text(data, key):
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > DEVICE_TEXT_LIMITS[key]:
        raise _Invalid(f'{key} must be a string of at most {DEVICE_TEXT_LIMITS[key]} characters')
    return value.strip() or None


def _coords(data):
    lat, lon = data.get('latitude'), data.get('longitude')
    if lat is None and lon is None:
        return None, None
    for name, value, bound in (('latitude', lat, 90), ('longitude', lon, 180)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                or not -bound <= value <= bound:
            raise _Invalid('latitude and longitude must be given together as valid coordinates')
    return lat, lon


def _parse_timestamp(value):
    """ISO 8601 string -> naive UTC datetime. Raises _Invalid."""
    if not isinstance(value, str) or len(value) > 64:
        raise _Invalid('timestamp must be an ISO 8601 string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise _Invalid('Invalid timestamp format, use ISO 8601')
    if parsed.tzinfo is not None:  # store naive UTC like every other timestamp
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def authenticate_device():
    """Authenticate device via API key in Authorization header.

    Expected header: Authorization: Bearer <device_id>:<api_key>
    Or: X-Device-ID and X-API-Key headers

    Returns:
        IoTDevice if authenticated, None otherwise
    """
    auth_header = request.headers.get('Authorization', '')

    device_id = None
    api_key = None

    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        if ':' in token:
            device_id, api_key = token.split(':', 1)

    if not device_id:
        device_id = request.headers.get('X-Device-ID')
        api_key = request.headers.get('X-API-Key')

    if not device_id or not api_key:
        return None

    device = IoTDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return None

    if not device.enabled or device.status == 'decommissioned':
        return None  # M-LIVE-02: decommissioned refuses even if `enabled` was left on

    if not device.verify_api_key(api_key):
        return None

    return device


@iot_bp.after_request
def count_rejected_telemetry(response):
    """Super Admin health: count refused telemetry (bad credentials vs bad payload). No payload kept."""
    if request.endpoint == 'iot.ingest_telemetry' and response.status_code >= 400:
        RUNTIME['telemetry_rejected_auth' if response.status_code == 401 else 'telemetry_rejected_invalid'] += 1
        RUNTIME['last_telemetry_rejected_at'] = datetime.utcnow()
    return response


@iot_bp.route('/telemetry', methods=['POST'])
@csrf.exempt  # device API: authenticated by its own API key header, no browser session/cookie involved
def ingest_telemetry():
    """Ingest sensor telemetry from an IoT device.

    Expected JSON:
    {
        "device_id": "ESP32-RIVER-001",  // optional if using headers
        "timestamp": "2024-01-15T10:30:00Z",  // optional, defaults to now
        "readings": [
            {
                "sensor_type": "water_level",
                "value": 2.35,
                "unit": "m"
            },
            {
                "sensor_type": "temperature",
                "value": 25.5,
                "unit": "°C"
            }
        ]
    }

    Authentication: Bearer <device_id>:<api_key> or X-Device-ID + X-API-Key headers
    """
    device = authenticate_device()
    if not device:
        return jsonify({'error': 'Invalid or missing device credentials'}), 401

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON payload'}), 400

    readings_data = data.get('readings')
    if not readings_data or not isinstance(readings_data, list):
        return jsonify({'error': 'Missing or invalid "readings" array'}), 400

    if len(readings_data) == 0:
        return jsonify({'error': 'At least one reading required'}), 400

    if len(readings_data) > 50:
        return jsonify({'error': 'Too many readings in single request (max 50)'}), 400

    recorded_at = None
    if data.get('timestamp') is not None:
        try:
            recorded_at = _parse_timestamp(data['timestamp'])
        except _Invalid as e:
            return jsonify({'error': str(e)}), 400

    received_at = datetime.utcnow()
    stored_readings = []
    errors = []

    for i, reading in enumerate(readings_data):
        if not isinstance(reading, dict):
            errors.append(f'Reading {i}: must be an object')
            continue
        sensor_type = reading.get('sensor_type')
        value = reading.get('value')
        unit = reading.get('unit')

        if sensor_type is None:
            errors.append(f'Reading {i}: missing sensor_type')
            continue
        if value is None:
            errors.append(f'Reading {i}: missing value')
            continue
        if unit is None:
            errors.append(f'Reading {i}: missing unit')
            continue
        if not isinstance(sensor_type, str) or not isinstance(unit, str):
            errors.append(f'Reading {i}: sensor_type and unit must be strings')
            continue

        # JSON numbers only: no booleans (True == 1), no numeric strings, no NaN/Infinity
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f'Reading {i}: value must be a finite number')
            continue
        value = float(value)

        valid, error = validate_sensor_reading(sensor_type, value, unit)
        if not valid:
            errors.append(f'Reading {i}: {error}')
            continue
        if device.kind == 'camera_node' and sensor_type not in CAMERA_NODE_SENSOR_TYPES:
            # a phone key must not be able to drive flood/motion rules (e.g. the river fallback)
            errors.append(f'Reading {i}: camera nodes may only send {", ".join(CAMERA_NODE_SENSOR_TYPES)}')
            continue

        quality = 'good'
        if sensor_type in ('water_level',):
            quality = 'good'

        reading_recorded_at = recorded_at or received_at
        sensor_reading = SensorReading(
            device_id=device.id,
            sensor_type=sensor_type,
            value=value,
            unit=unit,
            quality=quality,
            recorded_at=reading_recorded_at,
            received_at=received_at,
            raw_payload=json.dumps(reading),
        )
        db.session.add(sensor_reading)
        stored_readings.append(sensor_reading)

        if sensor_type == 'water_level' and device.district_id:
            process_water_level_reading(device, value, unit)

    if errors and not stored_readings:
        return jsonify({'error': 'All readings invalid', 'details': errors}), 400

    if device.district_id and any(r.sensor_type in ('vibration', 'tilt') for r in stored_readings):
        # Phase 3: Use seismic device-event state machine instead of direct Incident creation
        risk_service.evaluate_motion_with_state_machine(device)

    device.last_seen = received_at
    db.session.commit()

    response = {
        'status': 'accepted',
        'stored': len(stored_readings),
        'device_id': device.device_id,
        'timestamp': received_at.isoformat() + 'Z',
    }
    if errors:
        response['warnings'] = errors

    return jsonify(response), 201 if stored_readings else 400


def process_water_level_reading(device, water_level, unit):
    """Process a water level reading and update the associated river.
    
    Uses the explicit device.river_id relationship for reliable river association.
    Falls back to district-level lookup only if river_id is not set (backward compat).
    Creates/updates flood hazard events via the hazard event engine.
    """
    if unit != 'm':
        return

    river = None
    if device.river_id:
        river = db.session.get(River, device.river_id)
    elif device.district_id:
        river = River.query.filter_by(district_id=device.district_id).first()

    if not river:
        return

    # Always update current_level and last_updated
    river.current_level = water_level
    river.last_updated = datetime.utcnow()

    # Only compute status and alerts if danger_level is available
    if river.danger_level is not None:
        river.status = compute_river_status(water_level, river.danger_level)
        # M08 risk engine: M01 thresholds decide, recent readings add trend/corroboration;
        # a warranted assessment goes to hazard_event_service, which owns events and
        # hands state changes to notification_service (never one alert per reading)
        risk_service.evaluate_water_level(device, river, water_level)


@iot_bp.route('/latest', methods=['GET'])
def get_latest_telemetry():
    """Get latest sensor readings for dashboard polling.

    Query parameters:
        district_id: Filter by district
        sensor_type: Filter by sensor type
        device_id: Filter by device
        limit: Max readings to return (default 100)

    Requires: User authentication (session-based)
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    district_id = request.args.get('district_id', type=int)
    sensor_type = request.args.get('sensor_type')
    device_id = request.args.get('device_id')
    limit = max(1, min(request.args.get('limit', 100, type=int), 500))  # M10: LIMIT -1 = no limit in SQLite

    query = SensorReading.query.join(IoTDevice)

    if district_id:
        query = query.filter(IoTDevice.district_id == district_id)
    elif current_user.district_id and current_user.role == 'citizen':
        query = query.filter(IoTDevice.district_id == current_user.district_id)

    if sensor_type:
        query = query.filter(SensorReading.sensor_type == sensor_type)

    if device_id:
        query = query.filter(IoTDevice.device_id == device_id)

    readings = query.order_by(SensorReading.received_at.desc()).limit(limit).all()

    latest_by_device = {}
    for reading in readings:
        key = (reading.device_id, reading.sensor_type)
        if key not in latest_by_device:
            latest_by_device[key] = reading.to_dict()

    return jsonify({
        'readings': list(latest_by_device.values()),
        'count': len(latest_by_device),
    })


@iot_bp.route('/devices', methods=['GET'])
def list_devices():
    """List IoT devices. Linked authority: its own devices only. Admin: all, optional ?district_id."""
    error = _manager_error()
    if error:
        return error

    query = IoTDevice.query
    if current_user.role == 'authority':
        query = query.filter_by(authority_id=current_user.authority_id)
    elif request.args.get('district_id'):
        district_id = request.args.get('district_id', type=int)
        if not district_id:
            return jsonify({'error': 'district_id must be an integer'}), 400
        query = query.filter_by(district_id=district_id)

    devices = query.order_by(IoTDevice.created_at.desc()).all()
    return jsonify({'devices': [d.to_dict() for d in devices]})


@iot_bp.route('/devices', methods=['POST'])
def register_device():
    """Register a new IoT device (admin/authority only).

    Expected JSON:
    {
        "device_id": "ESP32-RIVER-001",
        "name": "Kamala River Sensor 1",
        "description": "Flood node: JSN-SR04T waterproof ultrasonic water level",
        "district_id": 1,
        "river_id": 5,  // optional: explicit river association
        "latitude": 27.27,
        "longitude": 85.91,
        "location_description": "Kamala River bridge, Kamalamai",
        "firmware_version": "1.0.0"
    }

    Returns the device with generated API key (only time it's shown).
    """
    error = _manager_error()
    if error:
        return error

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    device_id = data.get('device_id')
    if not device_id or not data.get('name') or not data.get('district_id'):
        return jsonify({'error': 'device_id, name, and district_id are required'}), 400
    try:
        if not isinstance(device_id, str) or not DEVICE_ID_RE.match(device_id):
            raise _Invalid('device_id must be 1-64 characters: letters, digits, ".", "_" or "-"')
        district_id = _strict_int(data.get('district_id'), 'district_id')
        river_id = _strict_int(data['river_id'], 'river_id') if data.get('river_id') is not None else None
        texts = {key: _text(data, key) for key in DEVICE_TEXT_LIMITS}
        if not texts['name']:
            raise _Invalid('name is required')
        latitude, longitude = _coords(data)
    except _Invalid as e:
        return jsonify({'error': str(e)}), 400

    if IoTDevice.query.filter_by(device_id=device_id).first():
        return jsonify({'error': 'Device ID already exists'}), 409

    if not db.session.get(District, district_id):
        return jsonify({'error': 'Invalid district_id'}), 400

    if river_id:
        river = db.session.get(River, river_id)
        if not river:
            return jsonify({'error': 'Invalid river_id'}), 400
        if river.district_id != district_id:
            return jsonify({'error': 'River does not belong to the specified district'}), 400

    authority_id = None
    if current_user.role == 'authority':
        authority_id = current_user.authority_id  # linked: checked by _manager_error
        auth = db.session.get(Authority, authority_id)
        if not auth or auth.district_id != district_id:
            return jsonify({'error': 'Authority not in this district'}), 403
    elif data.get('authority_id') is not None:
        try:
            authority_id = _strict_int(data['authority_id'], 'authority_id')
        except _Invalid as e:
            return jsonify({'error': str(e)}), 400
        auth = db.session.get(Authority, authority_id)
        if not auth or auth.district_id != district_id:
            return jsonify({'error': 'Invalid authority_id for district'}), 400

    api_key = IoTDevice.generate_api_key()
    api_key_hash = IoTDevice.hash_api_key(api_key)

    device = IoTDevice(
        device_id=device_id,
        name=texts['name'],
        description=texts['description'],
        district_id=district_id,
        authority_id=authority_id,
        river_id=river_id,
        latitude=latitude,
        longitude=longitude,
        location_description=texts['location_description'],
        firmware_version=texts['firmware_version'],
        api_key_hash=api_key_hash,
        status='active',
        enabled=True,
    )

    db.session.add(device)
    db.session.commit()

    response_data = device.to_dict(include_api_key=True)
    response_data['_plain_api_key'] = api_key

    return jsonify({
        'status': 'created',
        'device': response_data,
        'warning': 'Save the API key now. It will not be shown again.'
    }), 201


@iot_bp.route('/devices/<int:device_id>', methods=['PATCH'])
def update_device(device_id):
    """Update an owned device. Allowed: enabled, status, firmware_version, location_description,
    latitude+longitude, river_id. Anything else (device_id, keys, authority, district...) -> 400."""
    error = _manager_error()
    if error:
        return error

    device = db.session.get(IoTDevice, device_id)
    if device is None:
        return jsonify({'error': 'Not found'}), 404
    if not _can_manage_device(device):
        return jsonify({'error': 'Not authorized for this device'}), 403

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400
    unknown = sorted(set(data) - DEVICE_UPDATE_FIELDS)
    if unknown:
        return jsonify({'error': f"Field(s) not allowed: {', '.join(unknown)}"}), 400

    try:
        if 'enabled' in data and not isinstance(data['enabled'], bool):
            raise _Invalid('enabled must be true or false')
        if 'status' in data and data['status'] not in DEVICE_STATUSES:
            raise _Invalid(f'status must be one of {DEVICE_STATUSES}')
        texts = {key: _text(data, key) for key in ('firmware_version', 'location_description') if key in data}
        coords = None
        if 'latitude' in data or 'longitude' in data:
            coords = _coords(data)
            if None in coords:
                raise _Invalid('latitude and longitude must be given together as valid coordinates')
        river_id = None
        if data.get('river_id') is not None:
            river_id = _strict_int(data['river_id'], 'river_id')
            river = db.session.get(River, river_id)
            if not river:
                raise _Invalid('Invalid river_id')
            if river.district_id != device.district_id:
                raise _Invalid('River does not belong to the device district')
    except _Invalid as e:
        return jsonify({'error': str(e)}), 400

    if 'enabled' in data:
        device.enabled = data['enabled']
    if 'status' in data:
        device.status = data['status']
    for key, value in texts.items():
        setattr(device, key, value)
    if coords:
        device.latitude, device.longitude = coords
    if 'river_id' in data:
        device.river_id = river_id

    db.session.commit()
    return jsonify({'status': 'updated', 'device': device.to_dict()})


@iot_bp.route('/devices/<int:device_id>/rotate-key', methods=['POST'])
def rotate_device_key(device_id):
    """Rotate device API key (admin/authority only)."""
    error = _manager_error()
    if error:
        return error

    device = db.session.get(IoTDevice, device_id)
    if device is None:
        return jsonify({'error': 'Not found'}), 404
    if not _can_manage_device(device):
        return jsonify({'error': 'Not authorized for this device'}), 403

    new_api_key = IoTDevice.generate_api_key()
    device.api_key_hash = IoTDevice.hash_api_key(new_api_key)
    db.session.commit()

    return jsonify({
        'status': 'key_rotated',
        'device_id': device.device_id,
        'api_key': new_api_key,
        'warning': 'Save the new API key now. It will not be shown again.'
    })


# --- M-LIVE-02: camera-node field evidence ------------------------------------------------------

@iot_bp.route('/evidence', methods=['POST'])
@csrf.exempt  # device API: authenticated by its own API key header, no browser session/cookie involved
def ingest_evidence():
    """Field evidence from a camera_node device (future Android field node).

    Auth: same as telemetry (Bearer <device_id>:<api_key> or X-Device-ID + X-API-Key), kind camera_node.
    multipart/form-data:
      metadata  JSON object: client_event_id (required, 8-64 [A-Za-z0-9_-], reused on retries),
                captured_at (required, ISO 8601), latitude+longitude, gps_accuracy_m, gps_fix_at,
                device_score (0-1), model, model_version, app_version, battery_pct (0-100), network_type.
                Any other key -> 400; server-owned keys (severity, district_id, status, ...) -> 400.
      frame_0   required JPG/PNG/WEBP; frame_1, frame_2 optional (pre-event, peak, post-event).
    201 new evidence, 200 duplicate (same device + client_event_id), 400/413 invalid, 401 bad
    credentials, 403 not a camera node, 429 hourly limit.
    """
    device = authenticate_device()
    if not device:
        return jsonify({'error': 'Invalid or missing device credentials'}), 401
    if device.kind != 'camera_node':
        return jsonify({'error': 'This device is not a camera node'}), 403
    if not (request.mimetype or '').startswith('multipart/form-data'):
        return jsonify({'error': 'Content-Type must be multipart/form-data'}), 400

    try:
        unknown = sorted(set(request.form.keys()) - {'metadata'})
        if unknown:
            return jsonify({'error': f"Unknown form field(s): {', '.join(unknown)}"}), 400
        evidence, created = evidence_service.submit(device, request.form.get('metadata'), request.files)
    except RequestEntityTooLarge:
        return jsonify({'error': 'Upload is too large'}), 413
    except evidence_service.EvidenceError as e:
        return jsonify({'error': str(e)}), e.status
    except evidence_service.RateLimited:
        return jsonify({'error': 'Too many evidence uploads for this device; retry later'}), 429
    return jsonify({'success': True, 'duplicate': not created, 'evidence_id': evidence.id,
                    'incident_id': evidence.incident_id, 'status': evidence.status}), 201 if created else 200


def _visible_evidence(evidence_id):
    """(evidence, None) for an admin or the authority of its district; otherwise a 401/404 response
    (404 also for evidence that exists elsewhere, so ids don't leak)."""
    if not current_user.is_authenticated:
        return None, (jsonify({'error': 'Authentication required'}), 401)
    evidence = db.session.get(NodeEvidence, evidence_id)
    if evidence is None or not evidence_service.can_view(current_user, evidence):
        return None, (jsonify({'error': 'Not found'}), 404)
    return evidence, None


@iot_bp.route('/evidence/<int:evidence_id>/frames/<int:index>', methods=['GET'])
def evidence_frame(evidence_id, index):
    evidence, error = _visible_evidence(evidence_id)
    if error:
        return error
    path = evidence_service.frame_path(evidence, index)
    try:
        response = send_file(path, mimetype='image/jpeg', max_age=0) if path else None
    except FileNotFoundError:
        response = None
    if response is None:
        return jsonify({'error': 'Frame not available'}), 404
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Content-Disposition'] = 'inline'
    return response


@iot_bp.route('/evidence/<int:evidence_id>/review', methods=['POST'])
def review_evidence(evidence_id):
    """Body: {"status": "accepted" | "rejected"}. Reviews the evidence item only; the Incident
    lifecycle is still managed through /api/hazards. Session + CSRF (browser route)."""
    evidence, error = _visible_evidence(evidence_id)
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        evidence_service.review(current_user, evidence, data.get('status'))
    except evidence_service.EvidenceError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), e.status
    return jsonify({'evidence': evidence_service.to_dict(evidence)})
