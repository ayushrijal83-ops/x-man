"""Hazard Events API (M02) — /api/hazards.

All endpoints require login. Reads are open to any logged-in user (hazard info is
public-safety data, same as /rivers and /roads). Writes:
  - citizens may only report (source=citizen_report, always starts 'detected')
  - authorities manage events in their authority's district
  - admins manage all events
The event `source` is derived from the caller's role, never taken from the payload.
"""
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.extensions import db
from app.models import Incident
from app.models.incident import HAZARD_TYPES, HAZARD_SOURCES, HAZARD_STATUS, ACTIVE_STATUSES
from app.services.hazard_event_service import (
    report_hazard, transition_event_status, update_event, resolve_event, reject_event,
    get_active_events_for_district, get_events_by_type, get_events_by_source,
    get_event_statistics, _validate_hazard_type, _validate_severity,
    _validate_coordinates,
)

hazard_events_bp = Blueprint('hazard_events', __name__, url_prefix='/api/hazards')

MANAGER_ROLES = ('authority', 'admin')
TEXT_LIMITS = {'title': 200, 'location': 200, 'description': 5000}


def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return wrapper


def manager_required(f):
    @wraps(f)
    @api_login_required
    def wrapper(*args, **kwargs):
        if current_user.role not in MANAGER_ROLES:
            return jsonify({'error': 'Authority or admin role required'}), 403
        return f(*args, **kwargs)
    return wrapper


def _is_manager():
    return current_user.role in MANAGER_ROLES


def _serialize(incident):
    return incident.to_dict(include_internal=_is_manager())


def _authority_district_id():
    """District an authority user may manage (same rule as M01 device management)."""
    authority = current_user.authority
    return authority.district_id if authority else None


def _load_managed_incident(event_id):
    """Return (incident, error_response) for write endpoints."""
    incident = db.session.get(Incident, event_id)
    if not incident:
        return None, (jsonify({'error': 'Not found'}), 404)
    if current_user.role == 'authority':
        district_id = _authority_district_id()
        if district_id is None or incident.district_id != district_id:
            return None, (jsonify({'error': 'Not authorized for this district'}), 403)
    return incident, None


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _optional_int(data, key):
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{key} must be an integer')
    return value


def _optional_text(data, key):
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{key} must be a string')
    value = value.strip()
    if len(value) > TEXT_LIMITS[key]:
        raise ValueError(f'{key} must be at most {TEXT_LIMITS[key]} characters')
    return value or None


def _limit():
    return max(1, min(request.args.get('limit', 100, type=int), 500))


@hazard_events_bp.route('', methods=['GET'])
@api_login_required
def list_hazards():
    """List events. Filters: event_type, severity, source, status, district_id, limit.
    Defaults to active events when no status is given."""
    query = Incident.query
    for key in ('event_type', 'severity', 'source', 'status'):
        value = request.args.get(key)
        if value:
            query = query.filter(getattr(Incident, key) == value)
    district_id = request.args.get('district_id', type=int)
    if district_id:
        query = query.filter(Incident.district_id == district_id)
    if not request.args.get('status'):
        query = query.filter(Incident.status.in_(ACTIVE_STATUSES))
    incidents = query.order_by(Incident.detected_at.desc()).limit(_limit()).all()
    return jsonify({'events': [_serialize(i) for i in incidents]})


@hazard_events_bp.route('/statistics', methods=['GET'])
@manager_required
def get_statistics():
    return jsonify(get_event_statistics())


@hazard_events_bp.route('/<int:event_id>', methods=['GET'])
@api_login_required
def get_hazard(event_id):
    incident = db.session.get(Incident, event_id)
    if not incident:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(_serialize(incident))


@hazard_events_bp.route('', methods=['POST'])
@api_login_required
def create_hazard():
    """Report a hazard. Merges into a matching active event instead of duplicating.
    201 = new event, 200 = evidence added to existing event."""
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400

    event_type = data.get('event_type')
    if not event_type:
        return jsonify({'error': 'event_type is required'}), 400
    severity = data.get('severity', 'medium')

    try:
        _validate_hazard_type(event_type)
        _validate_severity(severity)
        district_id = _optional_int(data, 'district_id')
        river_id = _optional_int(data, 'river_id')
        road_segment_id = _optional_int(data, 'road_segment_id')
        latitude, longitude = data.get('latitude'), data.get('longitude')
        _validate_coordinates(latitude, longitude)
        fields = {k: _optional_text(data, k) for k in ('title', 'description', 'location')}
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    if current_user.role == 'citizen':
        source = 'citizen_report'
        district_id = district_id or current_user.district_id
    else:
        source = 'authority'
        if current_user.role == 'authority':
            own_district = _authority_district_id()
            if own_district is None:
                return jsonify({'error': 'Authority user not linked to an authority'}), 403
            if district_id and district_id != own_district:
                return jsonify({'error': 'Cannot create events outside your district'}), 403
            district_id = own_district

    try:
        incident, created = report_hazard(
            event_type, severity, source,
            district_id=district_id,
            river_id=river_id,
            road_segment_id=road_segment_id,
            latitude=latitude,
            longitude=longitude,
            source_reference=f'user_{current_user.id}',
            **fields,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'event': _serialize(incident), 'created': created}), 201 if created else 200


@hazard_events_bp.route('/<int:event_id>', methods=['PATCH'])
@manager_required
def update_hazard(event_id):
    """Edit an event. Allowed: severity, status, title, description, location, latitude+longitude."""
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400

    try:
        fields = {k: _optional_text(data, k) for k in TEXT_LIMITS if k in data}
        if 'latitude' in data or 'longitude' in data:
            _validate_coordinates(data.get('latitude'), data.get('longitude'))
            fields['latitude'], fields['longitude'] = data.get('latitude'), data.get('longitude')
        update_event(incident, severity=data.get('severity'), status=data.get('status'), **fields)
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'event': _serialize(incident)})


@hazard_events_bp.route('/<int:event_id>/status', methods=['POST', 'PATCH'])
@manager_required
def change_hazard_status(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    new_status = data.get('status')
    if not new_status:
        return jsonify({'error': 'status is required'}), 400
    try:
        old_status = transition_event_status(incident, new_status)
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'event': _serialize(incident), 'previous_status': old_status, 'new_status': new_status})


def _note(data, key):
    value = (data or {}).get(key)
    if value is not None and (not isinstance(value, str) or len(value) > 1000):
        raise ValueError(f'{key} must be a string of at most 1000 characters')
    return value


@hazard_events_bp.route('/<int:event_id>/resolve', methods=['POST'])
@manager_required
def resolve_hazard(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    try:
        resolve_event(incident, _note(_json_body(), 'resolution_notes'))
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'event': _serialize(incident)})


@hazard_events_bp.route('/<int:event_id>/reject', methods=['POST'])
@manager_required
def reject_hazard(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    try:
        reject_event(incident, _note(_json_body(), 'reason'))
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'event': _serialize(incident)})


@hazard_events_bp.route('/district/<int:district_id>/active', methods=['GET'])
@api_login_required
def get_district_active_events(district_id):
    return jsonify({'events': [_serialize(e) for e in get_active_events_for_district(district_id)]})


@hazard_events_bp.route('/types/<event_type>', methods=['GET'])
@api_login_required
def api_get_events_by_type(event_type):
    if event_type not in HAZARD_TYPES:
        return jsonify({'error': 'Invalid event type'}), 400
    status = request.args.get('status')
    if status and status not in HAZARD_STATUS:
        return jsonify({'error': 'Invalid status'}), 400
    events = get_events_by_type(event_type, status=status, limit=_limit())
    return jsonify({'events': [_serialize(e) for e in events]})


@hazard_events_bp.route('/sources/<source>', methods=['GET'])
@api_login_required
def get_events_by_source_endpoint(source):
    if source not in HAZARD_SOURCES:
        return jsonify({'error': 'Invalid source'}), 400
    return jsonify({'events': [_serialize(e) for e in get_events_by_source(source, limit=_limit())]})
