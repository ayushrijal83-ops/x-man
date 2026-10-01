"""Hazard Events API (M02) — /api/hazards.

All endpoints require login. Reads are open to any logged-in user (hazard info is
public-safety data, same as /rivers and /roads). Writes:
  - citizens may only report (source=citizen_report, always starts 'detected')
  - authorities manage events in their authority's district
  - admins manage all events
The event `source` is derived from the caller's role, never taken from the payload.
Citizens cannot set severity either: their reports are fixed at the service-level
citizen severity and never escalate an existing event (M05.1).
"""
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.extensions import db
from app.models import Incident
from app.models.incident import HAZARD_TYPES, HAZARD_SOURCES, HAZARD_STATUS, ACTIVE_STATUSES
from app.models.incident_response import IncidentResponseAction
from app.services import authority_response_service as response_service, risk_service
from app.services.hazard_event_service import (
    report_hazard, update_event, TransitionConflict,
    add_affected_district, remove_affected_district,
    affects_district, get_active_events_for_district, get_events_by_type, get_events_by_source,
    get_event_statistics, CITIZEN_REPORT_SEVERITY, _validate_hazard_type, _validate_severity,
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
    """Return (incident, error_response) for manager endpoints (M02 rule, authority_response_service.can_manage)."""
    incident = db.session.get(Incident, event_id)
    if not incident:
        return None, (jsonify({'error': 'Not found'}), 404)
    if not response_service.can_manage(current_user, incident):
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
        query = query.filter(affects_district(district_id))
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
    # Citizens: severity/status/source/incident_id in the body are ignored (same as /api/reports).
    is_citizen = current_user.role == 'citizen'
    severity = CITIZEN_REPORT_SEVERITY if is_citizen else data.get('severity', 'medium')

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

    if is_citizen:
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


@hazard_events_bp.route('/<int:event_id>/assessment', methods=['GET'])
@manager_required
def get_hazard_assessment(event_id):
    """M08: read-only multi-signal evidence assessment, computed server-side from evidence
    linked to this event. Authority: own district only (same rule as event management)."""
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    return jsonify({'hazard_id': incident.id,
                    'assessments': [a.to_dict() for a in risk_service.assess_incident(incident)]})


@hazard_events_bp.route('/<int:event_id>', methods=['PATCH'])
@manager_required
def update_hazard(event_id):
    """Edit an event. Allowed: severity, status (+ note), title, description, location, latitude+longitude.
    A status change follows the same M09 rules as /status (audited; resolved/rejected need a note)."""
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
        note = None
        if data.get('status') is not None:
            note = response_service.validate_status_request(incident, data['status'], data.get('note'))
        update_event(incident, severity=data.get('severity'), status=data.get('status'),
                     actor_id=current_user.id, note=note, **fields)
    except TransitionConflict as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'event': _serialize(incident)})


def _status_change(event_id, new_status=None, note_key='note'):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        response_service.reject_forbidden_fields(data)
        new_status = new_status or data.get('status')
        old_status = response_service.change_status(current_user, incident, new_status,
                                                     data.get(note_key, data.get('note')))
    except response_service.ResponseError as e:
        return jsonify({'error': str(e)}), e.status
    return jsonify({'event': _serialize(incident), 'previous_status': old_status, 'new_status': new_status})


@hazard_events_bp.route('/<int:event_id>/status', methods=['POST', 'PATCH'])
@manager_required
def change_hazard_status(event_id):
    """Body: {"status": ..., "note": ...}. Server validates current status, transition, scope and note."""
    return _status_change(event_id)


@hazard_events_bp.route('/<int:event_id>/resolve', methods=['POST'])
@manager_required
def resolve_hazard(event_id):
    """Body: {"resolution_notes": "..."} (required, internal)."""
    return _status_change(event_id, 'resolved', 'resolution_notes')


@hazard_events_bp.route('/<int:event_id>/reject', methods=['POST'])
@manager_required
def reject_hazard(event_id):
    """Body: {"reason": "..."} (required, internal)."""
    return _status_change(event_id, 'rejected', 'reason')


# --- M09 authority response records (manager-only, internal) -------------------------------

@hazard_events_bp.route('/<int:event_id>/status-history', methods=['GET'])
@manager_required
def get_status_history(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    return jsonify({'hazard_id': incident.id, 'status': incident.status,
                    'allowed_transitions': response_service.allowed_transitions(incident),
                    'status_history': [h.to_dict() for h in response_service.history(incident)]})


@hazard_events_bp.route('/<int:event_id>/investigations', methods=['GET', 'POST'])
@manager_required
def investigations(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    if request.method == 'GET':
        return jsonify({'hazard_id': incident.id,
                        'investigations': [n.to_dict() for n in response_service.investigations(incident)]})
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        response_service.reject_forbidden_fields(data)
        note = response_service.add_investigation(current_user, incident, data.get('note'))
    except response_service.ResponseError as e:
        return jsonify({'error': str(e)}), e.status
    return jsonify({'investigation': note.to_dict()}), 201


@hazard_events_bp.route('/<int:event_id>/response-actions', methods=['GET', 'POST'])
@manager_required
def response_actions(event_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    if request.method == 'GET':
        return jsonify({'hazard_id': incident.id,
                        'response_actions': [a.to_dict() for a in response_service.actions(incident)]})
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        action = response_service.add_action(current_user, incident, data)
    except response_service.ResponseError as e:
        return jsonify({'error': str(e)}), e.status
    return jsonify({'response_action': action.to_dict()}), 201


@hazard_events_bp.route('/<int:event_id>/response-actions/<int:action_id>', methods=['PATCH'])
@manager_required
def update_response_action(event_id, action_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    action = db.session.get(IncidentResponseAction, action_id)
    if action is None or action.incident_id != incident.id:
        return jsonify({'error': 'Not found'}), 404
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        response_service.update_action(current_user, incident, action, data)
    except response_service.ResponseError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), e.status
    return jsonify({'response_action': action.to_dict()})


def _affected_payload(incident):
    return {'hazard_id': incident.id,
            'primary_district_id': incident.district_id,
            'affected_districts': [{'id': d.id, 'name': d.name} for d in incident.affected_districts]}


@hazard_events_bp.route('/<int:event_id>/affected-districts', methods=['GET'])
@api_login_required
def list_affected_districts(event_id):
    incident = db.session.get(Incident, event_id)
    if not incident:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(_affected_payload(incident))


@hazard_events_bp.route('/<int:event_id>/affected-districts', methods=['POST'])
@manager_required
def add_affected_district_endpoint(event_id):
    """Body: {"district_id": <int>}. Authority: only hazards in its own district (M02 rule)."""
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    data = _json_body()
    if data is None:
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        district_id = _optional_int(data, 'district_id')
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if district_id is None:
        return jsonify({'error': 'district_id is required'}), 400
    try:
        sent = add_affected_district(incident, district_id)
    except LookupError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 404
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 409
    return jsonify({**_affected_payload(incident), 'notifications_sent': len(sent)}), 201


@hazard_events_bp.route('/<int:event_id>/affected-districts/<int:district_id>', methods=['DELETE'])
@manager_required
def remove_affected_district_endpoint(event_id, district_id):
    incident, error = _load_managed_incident(event_id)
    if error:
        return error
    try:
        remove_affected_district(incident, district_id)
    except LookupError as e:
        return jsonify({'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(_affected_payload(incident))


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
