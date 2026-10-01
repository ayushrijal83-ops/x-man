"""Admin control center queries (M12). Read-only aggregation + the few admin account actions.

Every number is a COUNT over real rows. Lists are paginated. Nothing here returns password
hashes, device API key hashes, push endpoints/keys or precise current-location coordinates.
"""
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import (Authority, District, Incident, IncidentResponseAction, IoTDevice, Notification,
                        PushSubscription, User)
from app.models.incident import ACTIVE_STATUSES
from app.models.user import EMERGENCY_ALERT_STATES
from app.services import account_service, emergency_dispatcher

PER_PAGE = 25
ACCOUNT_STATUSES = ('active', 'disabled')
AUTHORITY_STATUSES = ('active', 'disabled', 'unlinked')


def _search(columns, q):
    q = (q or '').strip().lower()[:100]
    if not q:
        return None
    return db.or_(*[db.func.lower(c).contains(q, autoescape=True) for c in columns])


def _push_users():
    """Ids of active users who opted in and still have at least one enabled subscription."""
    return db.session.query(PushSubscription.user_id).join(User, PushSubscription.user_id == User.id) \
        .filter(PushSubscription.enabled.is_(True), User.is_active.is_(True),
                User.emergency_alert_state == 'granted').distinct()


def overview():
    citizens = User.query.filter_by(role='citizen')
    since = datetime.utcnow() - timedelta(hours=24)
    return {
        'authorities': Authority.query.count(),
        'authority_accounts': User.query.filter_by(role='authority').count(),
        'citizens': citizens.count(),
        'disabled_accounts': User.query.filter(User.is_active.is_(False)).count(),
        'districts': District.query.count(),
        'active_hazards': Incident.query.filter(Incident.status.in_(ACTIVE_STATUSES)).count(),
        'push_users': _push_users().count(),
        'active_subscriptions': PushSubscription.query.filter_by(enabled=True).count(),
        'notifications_24h': Notification.query.filter(Notification.created_at >= since).count(),
        'recent_emergencies': Incident.query.filter(Incident.severity.in_(emergency_severities()))
        .order_by(Incident.detected_at.desc()).limit(8).all(),
        'push_configured': emergency_dispatcher.push_configured(),
    }


def emergency_severities():
    from app.models.incident import HAZARD_SEVERITY
    threshold = current_app.config['EMERGENCY_MIN_SEVERITY']
    return HAZARD_SEVERITY[HAZARD_SEVERITY.index(threshold):] if threshold in HAZARD_SEVERITY else ['critical']


def notification_status():
    """System-wide delivery health for /admin/notifications. Settings are read-only (environment)."""
    since = datetime.utcnow() - timedelta(hours=24)
    config = current_app.config
    states = dict(db.session.query(User.emergency_alert_state, db.func.count()).group_by(User.emergency_alert_state))
    recent = db.session.query(Notification.incident_id, Notification.type, Notification.severity,
                              db.func.count(), db.func.max(Notification.created_at)) \
        .filter(Notification.incident_id.isnot(None)) \
        .group_by(Notification.incident_id, Notification.type, Notification.severity) \
        .order_by(db.func.max(Notification.created_at).desc()).limit(15).all()
    return {
        'push_configured': emergency_dispatcher.push_configured(),
        'subject': config['VAPID_SUBJECT'],
        'min_severity': config['EMERGENCY_MIN_SEVERITY'],
        'allowed_hosts': config['WEB_PUSH_ALLOWED_HOSTS'],
        'alert_states': {s: states.get(s, 0) for s in EMERGENCY_ALERT_STATES},
        'subscriptions_enabled': PushSubscription.query.filter_by(enabled=True).count(),
        'subscriptions_disabled': PushSubscription.query.filter_by(enabled=False).count(),
        'subscriptions_failing': PushSubscription.query.filter(PushSubscription.enabled.is_(True),
                                                               PushSubscription.failure_count > 0).count(),
        'push_users': _push_users().count(),
        'sound_off': User.query.filter(User.emergency_sound_enabled.is_(False)).count(),
        'notifications_24h': Notification.query.filter(Notification.created_at >= since).count(),
        'recent': [{'incident': db.session.get(Incident, row[0]), 'type': row[1], 'severity': row[2],
                    'recipients': row[3], 'at': row[4],
                    'emergency': emergency_dispatcher.is_emergency(row[1], row[2]),
                    'pushed': emergency_dispatcher.pushable(row[1], row[2])} for row in recent],
    }


# --- citizens -----------------------------------------------------------------

def district_citizen_counts():
    """[(district, citizens, push_enabled)] for every district with citizens, largest first + unassigned."""
    push_ids = _push_users().subquery()
    rows = db.session.query(User.district_id, db.func.count(User.id),
                            db.func.count(push_ids.c.user_id)) \
        .outerjoin(push_ids, push_ids.c.user_id == User.id) \
        .filter(User.role == 'citizen').group_by(User.district_id).all()
    names = {d.id: d for d in District.query.filter(District.id.in_([r[0] for r in rows if r[0]]))}
    result = [{'district': names.get(r[0]), 'citizens': r[1], 'push_enabled': r[2]} for r in rows]
    return sorted(result, key=lambda r: (r['district'] is None, -r['citizens'],
                                         r['district'].name if r['district'] else ''))


def citizens(district_id=None, q=None, status=None, page=1):
    query = User.query.filter(User.role == 'citizen')
    if district_id == 0:
        query = query.filter(User.district_id.is_(None))
    elif district_id:
        query = query.filter(User.district_id == district_id)
    if status in ACCOUNT_STATUSES:
        query = query.filter(User.is_active.is_(status == 'active'))
    condition = _search([User.username, User.full_name, User.email], q)
    if condition is not None:
        query = query.filter(condition)
    pagination = query.order_by(User.created_at.desc(), User.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)
    return pagination, _subscription_counts([u.id for u in pagination.items])


def _subscription_counts(user_ids):
    if not user_ids:
        return {}
    return dict(db.session.query(PushSubscription.user_id, db.func.count())
                .filter(PushSubscription.user_id.in_(user_ids), PushSubscription.enabled.is_(True))
                .group_by(PushSubscription.user_id))


def citizen_detail(user):
    """Account view for an admin. Location: only whether/when it was shared, never coordinates."""
    return {
        'district': db.session.get(District, user.district_id) if user.district_id else None,
        'subscriptions': [s.summary() for s in user.push_subscriptions.order_by(PushSubscription.created_at.desc())],
        'notifications': Notification.query.filter_by(user_id=user.id).count(),
        'unread': Notification.query.filter_by(user_id=user.id, is_read=False).count(),
        'location_shared': user.current_latitude is not None,
    }


# --- authorities --------------------------------------------------------------

def authorities(district_id=None, q=None, status=None, page=1):
    query = Authority.query
    if district_id:
        query = query.filter(Authority.district_id == district_id)
    condition = _search([Authority.name, Authority.category], q)
    if condition is not None:
        query = query.filter(condition)
    linked = db.session.query(User.id).filter(User.authority_id == Authority.id, User.role == 'authority')
    if status == 'active':
        query = query.filter(linked.filter(User.is_active.is_(True)).exists())
    elif status == 'disabled':
        query = query.filter(linked.exists(), ~linked.filter(User.is_active.is_(True)).exists())
    elif status == 'unlinked':
        query = query.filter(~linked.exists())
    pagination = query.order_by(Authority.name, Authority.id).paginate(page=page, per_page=PER_PAGE,
                                                                      error_out=False)
    return pagination, _authority_rows([a.id for a in pagination.items])


def _authority_rows(ids):
    """Per-authority aggregates for one page: accounts, devices, push capability, last activity."""
    if not ids:
        return {}
    rows = {i: {'accounts': 0, 'active_accounts': 0, 'push_accounts': 0, 'devices': 0, 'last_login': None}
            for i in ids}
    push_ids = {uid for (uid,) in _push_users()}
    for user in User.query.filter(User.authority_id.in_(ids), User.role == 'authority'):
        row = rows[user.authority_id]
        row['accounts'] += 1
        row['active_accounts'] += bool(user.is_active)
        row['push_accounts'] += user.id in push_ids
        if user.last_login_at and (row['last_login'] is None or user.last_login_at > row['last_login']):
            row['last_login'] = user.last_login_at
    for authority_id, count in db.session.query(IoTDevice.authority_id, db.func.count()) \
            .filter(IoTDevice.authority_id.in_(ids)).group_by(IoTDevice.authority_id):
        rows[authority_id]['devices'] = count
    return rows


def authority_detail(authority):
    hazards = Incident.query.filter(Incident.status.in_(ACTIVE_STATUSES)).all()
    hazards = [h for h in hazards if authority.district_id in h.affected_district_ids]
    hazards.sort(key=lambda h: h.detected_at or datetime.min, reverse=True)
    accounts = User.query.filter_by(authority_id=authority.id, role='authority').order_by(User.username).all()
    return {
        'district': db.session.get(District, authority.district_id),
        'accounts': accounts,
        'push_counts': _subscription_counts([u.id for u in accounts]),
        'devices': IoTDevice.query.filter_by(authority_id=authority.id).order_by(IoTDevice.device_id).all(),
        'hazards': hazards[:20],
        'hazard_total': len(hazards),
        'open_actions': IncidentResponseAction.query.filter(
            IncidentResponseAction.incident_id.in_([h.id for h in hazards]),
            IncidentResponseAction.status.in_(('planned', 'in_progress'))).count() if hazards else 0,
    }


# --- account actions ----------------------------------------------------------

def _audit(admin, action, target):
    """No audit table exists; admin actions go to the application log (never secrets)."""
    current_app.logger.info('admin_action admin=%s action=%s target_user=%s', admin.id, action, target.id)


def set_active(admin, user, active):
    """Enable/disable a citizen or authority account. Admin accounts are not managed here."""
    if user.role not in ('citizen', 'authority') or user.id == admin.id:
        raise PermissionError('Only citizen and authority accounts can be enabled or disabled here.')
    user.is_active = bool(active)
    db.session.commit()
    _audit(admin, 'enable' if active else 'disable', user)


def reset_password(admin, user, temporary, confirm):
    """Admin sets a temporary password (stored only as a hash) the authority must change at next login.
    The existing password is never readable: only its one-way hash exists."""
    if user.role != 'authority':
        raise PermissionError('Password reset here is for authority accounts.')
    if temporary != confirm:
        raise ValueError('Temporary passwords do not match.')
    if len(temporary or '') < account_service.MIN_PASSWORD:
        raise ValueError('Temporary password must be at least 8 characters.')
    user.set_password(temporary)
    user.must_change_password = True
    db.session.commit()
    _audit(admin, 'reset_password', user)
