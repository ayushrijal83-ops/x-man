"""Authority Response System (M09): human investigation, response actions and resolution.

    route (thin) -> this service (authorization, validation, notes/actions, timeline)
                 -> hazard_event_service (status transitions + audit row, atomically)
                 -> notification_service (only via hazard_event_service, unchanged M03/M04 rules)

No detection, risk scoring, notification rows or severity changes here. Everything this module
returns is internal: it is only exposed through manager-only routes, never to citizens.
"""
from datetime import datetime

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.incident import ACTIVE_STATUSES, VALID_STATUS_TRANSITIONS
from app.models.incident_response import (
    ACTION_DESCRIPTION_MAX, ACTION_STATUSES, ACTION_TRANSITIONS, ACTION_TYPES, NOTE_MAX,
    IncidentInvestigation, IncidentResponseAction, IncidentStatusHistory,
)
from app.services import hazard_event_service

NOTE_REQUIRED_FOR = ('resolved', 'rejected')
# Never accepted from a client on M09 endpoints: the server derives or owns these.
FORBIDDEN_FIELDS = ('severity', 'source', 'risk_level', 'confidence', 'reporter_id', 'device_id', 'authority_id',
                    'author_id', 'changed_by', 'changed_by_id', 'incident_id', 'completed_at', 'created_at',
                    'previous_status', 'ai_label', 'ai_confidence', 'ai_model')


class ResponseError(ValueError):
    """Validation/authorization failure; `status` is the HTTP status to return."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def can_manage(user, incident):
    """M02 rule: admins manage everything; an authority manages events in its authority's district."""
    if user.role == 'admin':
        return True
    if user.role != 'authority' or user.authority is None:
        return False
    return incident.district_id is not None and incident.district_id == user.authority.district_id


def reject_forbidden_fields(data):
    present = [key for key in FORBIDDEN_FIELDS if key in data]
    if present:
        raise ResponseError(f"Field(s) not allowed: {', '.join(present)}")


def clean_text(value, name, limit, required=True):
    if value is None:
        if required:
            raise ResponseError(f'{name} is required')
        return None
    if not isinstance(value, str):
        raise ResponseError(f'{name} must be a string')
    value = value.strip()
    if not value:
        if required:
            raise ResponseError(f'{name} is required')
        return None
    if len(value) > limit:
        raise ResponseError(f'{name} must be at most {limit} characters')
    return value


def _require_active(incident):
    if incident.status not in ACTIVE_STATUSES:
        raise ResponseError(f'Hazard is {incident.status}; it is closed to new entries', status=409)


def validate_status_request(incident, new_status, note):
    """Transition first (clear error for impossible moves), then the note rule. Returns the clean note."""
    if not isinstance(new_status, str) or not new_status:
        raise ResponseError('status is required')
    if new_status not in VALID_STATUS_TRANSITIONS:
        raise ResponseError(f'Invalid status: {new_status}')
    if not incident.can_transition_to(new_status):
        raise ResponseError(f'Invalid transition from {incident.status} to {new_status}')
    return clean_text(note, 'note', NOTE_MAX, required=new_status in NOTE_REQUIRED_FOR)


def change_status(user, incident, new_status, note=None):
    """Validated, audited lifecycle change. resolved/rejected require a note (kept internal)."""
    db.session.refresh(incident)  # validate against the current row, not a stale object
    note = validate_status_request(incident, new_status, note)
    try:
        return hazard_event_service.transition_event_status(incident, new_status, actor_id=user.id, note=note)
    except hazard_event_service.TransitionConflict as e:
        raise ResponseError(str(e), status=409)
    except ValueError as e:
        raise ResponseError(str(e))


def add_investigation(user, incident, note):
    note = clean_text(note, 'note', NOTE_MAX)
    _require_active(incident)
    entry = IncidentInvestigation(incident_id=incident.id, author_id=user.id, note=note)
    db.session.add(entry)
    hazard_event_service._commit_or_rollback()
    return entry


def add_action(user, incident, data):
    reject_forbidden_fields(data)
    action_type = data.get('action_type')
    if action_type not in ACTION_TYPES:
        raise ResponseError(f'action_type must be one of {ACTION_TYPES}')
    status = data.get('status', 'planned')
    if status not in ACTION_STATUSES:
        raise ResponseError(f'status must be one of {ACTION_STATUSES}')
    description = clean_text(data.get('description'), 'description', ACTION_DESCRIPTION_MAX)
    _require_active(incident)
    action = IncidentResponseAction(incident_id=incident.id, author_id=user.id, action_type=action_type,
                                    description=description, status=status,
                                    completed_at=datetime.utcnow() if status == 'completed' else None)
    db.session.add(action)
    hazard_event_service._commit_or_rollback()
    return action


def update_action(user, incident, action, data):
    """Only status and description can change; completed/cancelled actions are final."""
    reject_forbidden_fields(data)
    unknown = set(data) - {'status', 'description'}
    if unknown:
        raise ResponseError(f"Field(s) not allowed: {', '.join(sorted(unknown))}")
    if not data:
        raise ResponseError('Nothing to update')
    _require_active(incident)
    if action.status not in ('planned', 'in_progress'):
        raise ResponseError(f'Action is {action.status}; it can no longer change', status=409)
    if 'description' in data:
        action.description = clean_text(data['description'], 'description', ACTION_DESCRIPTION_MAX)
    if 'status' in data:
        status = data['status']
        if status not in ACTION_STATUSES:
            raise ResponseError(f'status must be one of {ACTION_STATUSES}')
        if status != action.status:
            if status not in ACTION_TRANSITIONS[action.status]:
                raise ResponseError(f'Invalid action transition from {action.status} to {status}')
            action.status = status
            if status == 'completed':
                action.completed_at = datetime.utcnow()
    hazard_event_service._commit_or_rollback()
    return action


def history(incident):
    return IncidentStatusHistory.query.filter_by(incident_id=incident.id) \
        .options(joinedload(IncidentStatusHistory.changed_by)).order_by(IncidentStatusHistory.created_at, IncidentStatusHistory.id).all()


def investigations(incident):
    return IncidentInvestigation.query.filter_by(incident_id=incident.id) \
        .options(joinedload(IncidentInvestigation.author)).order_by(IncidentInvestigation.created_at, IncidentInvestigation.id).all()


def actions(incident):
    return IncidentResponseAction.query.filter_by(incident_id=incident.id) \
        .options(joinedload(IncidentResponseAction.author)).order_by(IncidentResponseAction.created_at, IncidentResponseAction.id).all()


def timeline(incident):
    """Chronological record: detection (from the event itself, so legacy rows work too),
    every audited status change, every note, every action created."""
    items = [{'kind': 'detected', 'at': incident.detected_at, 'status': 'detected', 'by': None, 'text': None}]
    items += [{'kind': 'status', 'at': h.created_at, 'status': h.new_status, 'previous': h.previous_status,
               'by': h.changed_by.username if h.changed_by else None, 'text': h.note} for h in history(incident)]
    items += [{'kind': 'note', 'at': n.created_at, 'by': n.author.username if n.author else None, 'text': n.note}
              for n in investigations(incident)]
    items += [{'kind': 'action', 'at': a.created_at, 'by': a.author.username if a.author else None,
               'text': a.description, 'action_type': a.action_type, 'action_status': a.status}
              for a in actions(incident)]
    return sorted(items, key=lambda item: item['at'] or datetime.min)


def allowed_transitions(incident):
    return list(VALID_STATUS_TRANSITIONS.get(incident.status, []))
