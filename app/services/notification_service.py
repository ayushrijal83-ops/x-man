"""Notification Service (M03).

The only place notifications are created. Hazard notifications are emitted by
hazard_event_service when an event's state actually changes (detected,
severity escalated, confirmed, resolved) — never per API call or per reading.

Functions add to the session but do not commit; the caller owns the transaction.
In-app only: no SMS/email/push (later milestones).
"""
from app.extensions import db
from app.models import Authority, Notification, User
from app.models.incident import HAZARD_SEVERITY
from app.models.notification import NOTIFICATION_TYPES, LEGACY_NOTIFICATION_TYPES

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


def create_notification(user_id, type, title, message=None, link=None, severity=None, incident_id=None):
    if type not in NOTIFICATION_TYPES and type not in LEGACY_NOTIFICATION_TYPES:
        raise ValueError(f'Invalid notification type: {type}')
    if not title:
        raise ValueError('title is required')
    if severity is not None and severity not in HAZARD_SEVERITY:
        raise ValueError(f'Invalid severity: {severity}')
    notification = Notification(user_id=user_id, type=type, title=title[:200], message=message,
                                link=link, severity=severity, incident_id=incident_id, is_read=False)
    db.session.add(notification)
    return notification


def hazard_recipients(incident):
    """User ids to notify about a hazard.

    district set -> every user whose home district it is (citizens and authority
    users) + authority users whose Authority is responsible for that district;
    always -> admins. No district -> admins only. (Affected-area targeting: M04.)
    """
    conditions = [User.role == 'admin']
    if incident.district_id:
        responsible = db.session.query(Authority.id).filter(Authority.district_id == incident.district_id)
        conditions += [User.district_id == incident.district_id, User.authority_id.in_(responsible)]
    return [uid for (uid,) in db.session.query(User.id).filter(db.or_(*conditions)).all()]


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
    return title, ' · '.join(dict.fromkeys(p for p in parts if p))


def notify_hazard(incident, ntype):
    """Send one lifecycle notification per recipient. Returns the new notifications.

    Dedup: a (hazard, type) pair is sent once; escalations once per severity
    level. Repeated identical state changes therefore produce nothing.
    """
    if ntype not in _VERBS:
        raise ValueError(f'Not a hazard notification type: {ntype}')
    already = Notification.query.filter_by(incident_id=incident.id, type=ntype)
    if ntype == 'hazard_escalated':
        already = already.filter_by(severity=incident.severity)
    if already.first():
        return []

    title, message = _compose(incident, ntype)
    link = _link_for(incident)
    return [create_notification(uid, ntype, title, message, link, incident.severity, incident.id)
            for uid in hazard_recipients(incident)]


def notify_hazard_detected(incident):
    return notify_hazard(incident, 'hazard_detected')


def notify_hazard_escalated(incident, previous_severity):
    """Only when severity actually went up."""
    if HAZARD_SEVERITY.index(incident.severity) <= HAZARD_SEVERITY.index(previous_severity or 'low'):
        return []
    return notify_hazard(incident, 'hazard_escalated')


def notify_hazard_confirmed(incident):
    return notify_hazard(incident, 'hazard_confirmed')


def notify_hazard_resolved(incident):
    return notify_hazard(incident, 'hazard_resolved')


# --- per-user access (always scoped by user_id: no IDOR) --------------------

def get_user_notifications(user_id, unread_only=False, limit=50):
    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


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
