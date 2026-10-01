"""Notification Service (M03, M04).

The only place notifications are created. Hazard notifications are emitted by
hazard_event_service when an event's state actually changes (detected,
severity escalated, confirmed, resolved) — never per API call or per reading.

M04: recipients come from every affected district (primary + additional), and
dedup is per user: a user gets a given (hazard, type[, severity]) alert at most
once. Python filters first; the unique (user_id, dedup_key) index is the final
defence.

Functions add to the session but do not commit; the caller owns the transaction.
M12: rows created here are also queued for Web Push (emergency_dispatcher); no SMS/email yet.
"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Authority, Incident, IncidentAffectedDistrict, Notification, User
from app.models.incident import HAZARD_SEVERITY
from app.models.notification import NOTIFICATION_TYPES, LEGACY_NOTIFICATION_TYPES
from app.services import emergency_dispatcher

HAZARD_LABELS = {
    'flood': 'Flood',
    # MPU6050-class prototypes detect abnormal ground motion, not certified quakes
    'earthquake': 'Earthquake / abnormal ground motion',
    'landslide': 'Landslide',
    'road_damage': 'Road damage',
}

_VERBS = {
    'hazard_detected': 'detected',
    'hazard_escalated': 'escalated',
    'hazard_confirmed': 'confirmed',
    'hazard_resolved': 'resolved',
}


def _build(user_id, type, title, message=None, link=None, severity=None, incident_id=None, dedup_key=None):
    if type not in NOTIFICATION_TYPES and type not in LEGACY_NOTIFICATION_TYPES:
        raise ValueError(f'Invalid notification type: {type}')
    if not title:
        raise ValueError('title is required')
    if severity is not None and severity not in HAZARD_SEVERITY:
        raise ValueError(f'Invalid severity: {severity}')
    return Notification(user_id=user_id, type=type, title=title[:200], message=message, link=link,
                        severity=severity, incident_id=incident_id, dedup_key=dedup_key, is_read=False)


def create_notification(user_id, type, title, message=None, link=None, severity=None, incident_id=None):
    """Validate and add one notification to the session (no dedup key)."""
    notification = _build(user_id, type, title, message, link, severity, incident_id)
    db.session.add(notification)
    return notification


def _save(notifications):
    """Insert notifications, skipping any that hit the unique dedup index.

    Savepoints keep a duplicate (e.g. two concurrent writers) from rolling back
    the caller's hazard change. Returns the rows actually saved.
    """
    try:
        with db.session.begin_nested():
            db.session.add_all(notifications)
        return notifications
    except IntegrityError:
        saved = []
        for notification in notifications:
            try:
                with db.session.begin_nested():
                    db.session.add(notification)
                saved.append(notification)
            except IntegrityError:
                pass
        return saved


def hazard_recipients(incident):
    """User ids to notify about a hazard.

    For every affected district: users whose home district it is (citizens and
    authority users) + authority users whose Authority is responsible for it.
    Always: admins. No affected district -> admins only.
    """
    district_ids = incident.affected_district_ids
    conditions = [User.role == 'admin']
    if district_ids:
        responsible = db.session.query(Authority.id).filter(Authority.district_id.in_(district_ids))
        conditions += [User.district_id.in_(district_ids), User.authority_id.in_(responsible)]
    return [uid for (uid,) in db.session.query(User.id).filter(db.or_(*conditions)).all()]


def dedup_key(incident, ntype):
    """Same user + same key = same alert. Escalations are distinct per severity level."""
    if ntype == 'hazard_escalated':
        return f'{incident.id}:{ntype}:{incident.severity}'
    return f'{incident.id}:{ntype}'


def _link_for(incident):
    if incident.river_id and incident.district_id:
        return f'/rivers/status?district_id={incident.district_id}'
    if incident.district_id:
        return f'/district/{incident.district_id}'
    return None


def _compose(incident, ntype):
    label = HAZARD_LABELS.get(incident.event_type, incident.event_type)
    place = incident.district.name if incident.district else None
    if ntype == 'hazard_escalated':
        title = f'{label} escalated to {incident.severity.upper()}'
    else:
        title = f'{label} {_VERBS[ntype]}'
    if place:
        title += f' in {place}'
    # Only public fields: never description (free text, resolution notes) or source_reference.
    parts = [incident.title, incident.river.name if incident.river else None,
             incident.road_segment.name if incident.road_segment else None,
             f'Severity: {incident.severity}']
    affected = incident.affected_districts
    if len(affected) > 1:
        parts.append('Affected: ' + ', '.join(d.name for d in affected))
    return title, ' · '.join(dict.fromkeys(p for p in parts if p))


def notify_hazard(incident, ntype, exclude_user_ids=()):
    """Send a lifecycle notification to every recipient who hasn't had it yet.

    Returns the new notifications. Active-hazard alerts (detected, escalated,
    confirmed) are never sent for resolved/rejected events. `exclude_user_ids`
    skips e.g. the citizen whose own report created the hazard.
    """
    if ntype not in _VERBS:
        raise ValueError(f'Not a hazard notification type: {ntype}')
    if ntype != 'hazard_resolved' and not incident.is_active:
        return []

    key = dedup_key(incident, ntype)
    already = {uid for (uid,) in db.session.query(Notification.user_id).filter(Notification.dedup_key == key)}
    recipients = [uid for uid in hazard_recipients(incident)
                  if uid not in already and uid not in exclude_user_ids]
    if not recipients:
        return []
    title, message = _compose(incident, ntype)
    link = _link_for(incident)
    saved = _save([_build(uid, ntype, title, message, link, incident.severity, incident.id, key)
                   for uid in recipients])
    emergency_dispatcher.queue(saved)  # M12: Web Push for these rows, after the caller commits
    return saved


def notify_hazard_detected(incident, exclude_user_ids=()):
    return notify_hazard(incident, 'hazard_detected', exclude_user_ids)


def notify_hazard_escalated(incident, previous_severity):
    """Only when severity actually went up."""
    if HAZARD_SEVERITY.index(incident.severity) <= HAZARD_SEVERITY.index(previous_severity or 'low'):
        return []
    return notify_hazard(incident, 'hazard_escalated')


def notify_hazard_confirmed(incident):
    return notify_hazard(incident, 'hazard_confirmed')


def notify_hazard_resolved(incident):
    return notify_hazard(incident, 'hazard_resolved')


def notify_area_expanded(incident):
    """After a district is added: bring newly covered users up to the current state.

    Users already notified get nothing new (per-user dedup).
    """
    sent = notify_hazard(incident, 'hazard_detected')
    if incident.status in ('confirmed', 'response'):  # M09: response follows confirmation
        sent += notify_hazard(incident, 'hazard_confirmed')
    return sent


_REPORT_MESSAGES = {
    'submitted': ('Your {label} report was received',
                  'Thank you. Authorities will review it. This is a receipt, not a hazard alert.'),
    'accepted': ('Your {label} report was accepted', 'An authority reviewed your report and accepted it.'),
    'rejected': ('Your {label} report was not accepted', 'An authority reviewed your report and did not accept it.'),
}


def notify_report_update(report):
    """Receipt/review notice to the reporter only (M05). Separate from hazard alerts."""
    title, message = _REPORT_MESSAGES[report.status]
    label = HAZARD_LABELS.get(report.hazard_type, report.hazard_type).lower()
    return _save([_build(report.reporter_id, 'report_update', title.format(label=label), message,
                         '/reports/mine', dedup_key=f'report:{report.id}:{report.status}')])


# --- per-user access (always scoped by user_id: no IDOR) --------------------

def get_user_notifications(user_id, unread_only=False, limit=50):
    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    # M10: to_dict() reads the hazard, its district and extra districts; load them up front
    # instead of 2-3 lazy queries per notification
    return query.options(
        joinedload(Notification.incident).joinedload(Incident.district),
        joinedload(Notification.incident).selectinload(Incident.additional_districts)
        .joinedload(IncidentAffectedDistrict.district),
    ).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


def unread_count(user_id):
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def mark_as_read(user_id, notification_id):
    """Returns the notification, or None if it doesn't exist or isn't this user's."""
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if notification and not notification.is_read:
        notification.is_read = True
        db.session.commit()
    return notification


def mark_all_as_read(user_id):
    updated = Notification.query.filter_by(user_id=user_id, is_read=False) \
        .update({'is_read': True}, synchronize_session=False)
    db.session.commit()
    return updated
