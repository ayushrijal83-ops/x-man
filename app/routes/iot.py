"""IoT API blueprint for hardware device telemetry ingestion."""
from flask import Blueprint, jsonify, request, g
from app.extensions import db
from app.models import IoTDevice, SensorReading, District, Authority
from app.services.risk_engine import (
    validate_sensor_reading,
    assess_water_level_risk,
    compute_river_status,
)
from app.services.hazard_event_service import auto_create_flood_event_from_river
from datetime import datetime
import json

iot_bp = Blueprint('iot', __name__, url_prefix='/api/iot')


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

    if not device.enabled:
        return None

    if not device.verify_api_key(api_key):
        return None

    return device


@iot_bp.route('/telemetry', methods=['POST'])
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

    data = request.get_json()
    if data is None:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    readings_data = data.get('readings')
    if not readings_data or not isinstance(readings_data, list):
        return jsonify({'error': 'Missing or invalid "readings" array'}), 400

    if len(readings_data) == 0:
        return jsonify({'error': 'At least one reading required'}), 400

    if len(readings_data) > 50:
        return jsonify({'error': 'Too many readings in single request (max 50)'}), 400

    timestamp_str = data.get('timestamp')
    recorded_at = None
    if timestamp_str:
        try:
            recorded_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid timestamp format, use ISO 8601'}), 400

    received_at = datetime.utcnow()
    stored_readings = []
    errors = []

    for i, reading in enumerate(readings_data):
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

        try:
            value = float(value)
        except (ValueError, TypeError):
            errors.append(f'Reading {i}: value must be a number')
            continue

        valid, error = validate_sensor_reading(sensor_type, value, unit)
        if not valid:
            errors.append(f'Reading {i}: {error}')
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

    from app.models import River

    river = None
    if device.river_id:
        river = River.query.get(device.river_id)
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

        risk = assess_water_level_risk(water_level, river.danger_level)
        
        if risk['alert_required'] and risk['risk_level'] >= 2:  # rising=2, flooding=3
            # M02: threshold crossing becomes evidence for a flood hazard event
            auto_create_flood_event_from_river(river, risk, device)
            # M01 behaviour, unchanged (notification rework is M03)
            create_river_alert(device, river, risk)


def create_river_alert(device, river, risk):
    """Create a notification/alert for rising/flooding river."""
    from app.models import Notification, User

    users = User.query.filter_by(district_id=river.district_id).all()
    for user in users:
        notification = Notification(
            user_id=user.id,
            type='river_alert',
            title=f"River Alert: {river.name}",
            message=f"{river.name} is {risk['status']} at {river.current_level}m "
                    f"({risk['percentage']:.0f}% of danger level). {risk['reason']}",
            link=f"/rivers/status?district_id={river.district_id}",
        )
        db.session.add(notification)


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
    from flask_login import current_user, login_required

    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    district_id = request.args.get('district_id', type=int)
    sensor_type = request.args.get('sensor_type')
    device_id = request.args.get('device_id')
    limit = min(request.args.get('limit', 100, type=int), 500)

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
    """List IoT devices (admin/authority only)."""
    from flask_login import current_user, login_required

    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    if current_user.role not in ('authority', 'admin'):
        return jsonify({'error': 'Authority or admin role required'}), 403

    query = IoTDevice.query

    if current_user.role == 'authority' and current_user.authority_id:
        query = query.filter_by(authority_id=current_user.authority_id)
    elif district_id := request.args.get('district_id', type=int):
        query = query.filter_by(district_id=district_id)
    elif current_user.district_id:
        query = query.filter_by(district_id=current_user.district_id)

    devices = query.order_by(IoTDevice.created_at.desc()).all()
    return jsonify({'devices': [d.to_dict() for d in devices]})


@iot_bp.route('/devices', methods=['POST'])
def register_device():
    """Register a new IoT device (admin/authority only).

    Expected JSON:
    {
        "device_id": "ESP32-RIVER-001",
        "name": "Kamala River Sensor 1",
        "description": "HC-SR04 ultrasonic water level sensor",
        "district_id": 1,
        "river_id": 5,  // optional: explicit river association
        "latitude": 27.27,
        "longitude": 85.91,
        "location_description": "Kamala River bridge, Kamalamai",
        "firmware_version": "1.0.0"
    }

    Returns the device with generated API key (only time it's shown).
    """
    from flask_login import current_user, login_required

    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    if current_user.role not in ('authority', 'admin'):
        return jsonify({'error': 'Authority or admin role required'}), 403

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    device_id = data.get('device_id')
    name = data.get('name')
    district_id = data.get('district_id')
    river_id = data.get('river_id')

    if not device_id or not name or not district_id:
        return jsonify({'error': 'device_id, name, and district_id are required'}), 400

    if IoTDevice.query.filter_by(device_id=device_id).first():
        return jsonify({'error': 'Device ID already exists'}), 409

    district = District.query.get(district_id)
    if not district:
        return jsonify({'error': 'Invalid district_id'}), 400

    if river_id:
        river = River.query.get(river_id)
        if not river:
            return jsonify({'error': 'Invalid river_id'}), 400
        if river.district_id != district_id:
            return jsonify({'error': 'River does not belong to the specified district'}), 400

    authority_id = None
    if current_user.role == 'authority':
        authority_id = current_user.authority_id
        if not authority_id:
            return jsonify({'error': 'Authority user not linked to an authority'}), 400
        auth = Authority.query.get(authority_id)
        if auth and auth.district_id != district_id:
            return jsonify({'error': 'Authority not in this district'}), 403
    elif data.get('authority_id'):
        authority_id = data['authority_id']
        auth = Authority.query.get(authority_id)
        if not auth or auth.district_id != district_id:
            return jsonify({'error': 'Invalid authority_id for district'}), 400

    api_key = IoTDevice.generate_api_key()
    api_key_hash = IoTDevice.hash_api_key(api_key)

    device = IoTDevice(
        device_id=device_id,
        name=name,
        description=data.get('description'),
        district_id=district_id,
        authority_id=authority_id,
        river_id=river_id,
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        location_description=data.get('location_description'),
        firmware_version=data.get('firmware_version'),
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
    """Update device status/enabled state (admin/authority only)."""
    from flask_login import current_user, login_required

    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    if current_user.role not in ('authority', 'admin'):
        return jsonify({'error': 'Authority or admin role required'}), 403

    device = IoTDevice.query.get_or_404(device_id)

    if current_user.role == 'authority' and device.authority_id != current_user.authority_id:
        return jsonify({'error': 'Not authorized for this device'}), 403

    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    if 'enabled' in data:
        device.enabled = bool(data['enabled'])

    if 'status' in data:
        valid_statuses = ['active', 'inactive', 'maintenance', 'decommissioned']
        if data['status'] in valid_statuses:
            device.status = data['status']

    if 'firmware_version' in data:
        device.firmware_version = data['firmware_version']

    if 'location_description' in data:
        device.location_description = data['location_description']

    if 'latitude' in data and 'longitude' in data:
        device.latitude = data['latitude']
        device.longitude = data['longitude']

    if 'river_id' in data:
        river_id = data['river_id']
        if river_id is not None:
            river = River.query.get(river_id)
            if not river:
                return jsonify({'error': 'Invalid river_id'}), 400
            if river.district_id != device.district_id:
                return jsonify({'error': 'River does not belong to the device district'}), 400
        device.river_id = river_id

    db.session.commit()
    return jsonify({'status': 'updated', 'device': device.to_dict()})


@iot_bp.route('/devices/<int:device_id>/rotate-key', methods=['POST'])
def rotate_device_key(device_id):
    """Rotate device API key (admin/authority only)."""
    from flask_login import current_user, login_required

    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    if current_user.role not in ('authority', 'admin'):
        return jsonify({'error': 'Authority or admin role required'}), 403

    device = IoTDevice.query.get_or_404(device_id)

    if current_user.role == 'authority' and device.authority_id != current_user.authority_id:
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