"""Super Admin Control Center queries and actions (M12, extended for the Super Admin release).

The `admin` role IS the Super Admin: there is no higher application role and no second login.
Every number is a COUNT over real rows. Lists are paginated. Nothing here returns password
hashes, device API keys or their hashes, push endpoints/keys, the VAPID private key or precise
current-location coordinates of citizens.

Actions mutate and return a safe one-line summary; the route records it in AuditLog and commits
(see routes/admin.py _act), so the change and its audit row land together.
"""
import secrets
import threading
import time
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import RUNTIME, db
from app.models import (AuditLog, Authority, CitizenReport, District, Incident, IncidentAffectedDistrict,
                        IncidentResponseAction, IncidentStatusHistory, IoTDevice, Notification, PushSubscription,
                        SensorReading, User)
from app.models.audit_log import AUDIT_ACTIONS, AUDIT_TARGETS, REASON_MAX
from app.models.citizen_report import AI_STATUS, REPORT_STATUS, VISUAL_HAZARD_TYPES
from app.models.incident import ACTIVE_STATUSES, HAZARD_SEVERITY, HAZARD_STATUS, HAZARD_TYPES, VALID_STATUS_TRANSITIONS
from app.models.user import EMERGENCY_ALERT_STATES
from app.services import account_service, citizen_report_service, emergency_dispatcher, hazard_event_service
from app.services.dashboard_service import ONLINE_SECONDS, STALE_SECONDS, freshness, latest_readings

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
    ids = [u.id for u in pagination.items]
    return pagination, _subscription_counts(ids), citizen_report_counts(ids)


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
        'reports': CitizenReport.query.filter_by(reporter_id=user.id)
        .order_by(CitizenReport.created_at.desc()).limit(20).all(),
        'report_total': CitizenReport.query.filter_by(reporter_id=user.id).count(),
        'audit': audit_for('user', [user.id]),
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
        'audit': sorted(audit_for('authority', [authority.id]) + audit_for('user', [u.id for u in accounts]),
                        key=lambda e: e.id, reverse=True)[:20],
    }




def citizen_report_counts(user_ids):
    if not user_ids:
        return {}
    return dict(db.session.query(CitizenReport.reporter_id, db.func.count())
                .filter(CitizenReport.reporter_id.in_(user_ids)).group_by(CitizenReport.reporter_id))


def audit_for(target_type, target_ids, limit=20):
    return AuditLog.query.filter(AuditLog.target_type == target_type,
                                 AuditLog.target_id.in_([str(i) for i in target_ids])) \
        .order_by(AuditLog.id.desc()).limit(limit).all()


# --- dashboard ----------------------------------------------------------------

def _count_by(column, *filters):
    return dict(db.session.query(column, db.func.count()).filter(*filters).group_by(column).all())


def user_counts():
    """{'citizen'|'authority'|'admin': {'total', 'active', 'disabled'}} from the users table."""
    counts = {role: {'total': 0, 'active': 0, 'disabled': 0} for role in ('citizen', 'authority', 'admin')}
    for role, active, n in db.session.query(User.role, User.is_active, db.func.count()) \
            .group_by(User.role, User.is_active):
        if role in counts:
            counts[role]['total'] += n
            counts[role]['active' if active else 'disabled'] += n
    return counts


DEVICE_STATES = ('online', 'stale', 'offline', 'never', 'disabled')


def device_state(device, now=None):
    """UI label only, never written back: 'disabled' (telemetry refused) wins, otherwise the same
    last_seen freshness rule as /monitoring (online / stale / offline / never)."""
    if not device.enabled:
        return 'disabled'
    return freshness(device.last_seen, now or datetime.utcnow())[0]


def _state_filter(state, now):
    enabled = IoTDevice.enabled.is_(True)
    online_cut, stale_cut = now - timedelta(seconds=ONLINE_SECONDS), now - timedelta(seconds=STALE_SECONDS)
    return {
        'disabled': db.or_(IoTDevice.enabled.is_(False), IoTDevice.enabled.is_(None)),
        'never': db.and_(enabled, IoTDevice.last_seen.is_(None)),
        'online': db.and_(enabled, IoTDevice.last_seen >= online_cut),
        'stale': db.and_(enabled, IoTDevice.last_seen < online_cut, IoTDevice.last_seen >= stale_cut),
        'offline': db.and_(enabled, IoTDevice.last_seen < stale_cut),
    }[state]


def iot_summary():
    now = datetime.utcnow()
    states = {state: IoTDevice.query.filter(_state_filter(state, now)).count() for state in DEVICE_STATES}
    by_district = db.session.query(District.name, db.func.count(IoTDevice.id)) \
        .join(IoTDevice, IoTDevice.district_id == District.id).group_by(District.name) \
        .order_by(db.func.count(IoTDevice.id).desc(), District.name).all()
    by_sensor = db.session.query(SensorReading.sensor_type, db.func.count(db.distinct(SensorReading.device_id))) \
        .group_by(SensorReading.sensor_type).order_by(SensorReading.sensor_type).all()
    return {'total': IoTDevice.query.count(), 'enabled': IoTDevice.query.filter(IoTDevice.enabled.is_(True)).count(),
            'disabled': states['disabled'], 'states': states,
            'last_telemetry': db.session.query(db.func.max(SensorReading.received_at)).scalar(),
            'by_district': by_district, 'by_sensor': by_sensor}


def hazard_overview():
    active = Incident.status.in_(ACTIVE_STATUSES)
    by_district = {}
    for incident in Incident.query.filter(active):  # every affected district, not only the primary one
        for district in incident.affected_districts:
            by_district[district.name] = by_district.get(district.name, 0) + 1
    severity, types = _count_by(Incident.severity, active), _count_by(Incident.event_type, active)
    return {'active': Incident.query.filter(active).count(),
            'by_severity': {s: severity.get(s, 0) for s in reversed(HAZARD_SEVERITY)},
            'by_type': {t: types.get(t, 0) for t in HAZARD_TYPES},
            'by_district': sorted(by_district.items(), key=lambda kv: (-kv[1], kv[0]))}


def ai_disagreement():
    """The model named a *different* visual hazard than the citizen chose. 'unknown' is inconclusive,
    not disagreement. Evidence for reviewers only: it never changes the report or the hazard."""
    return db.and_(CitizenReport.ai_status == 'completed', CitizenReport.ai_label.in_(VISUAL_HAZARD_TYPES),
                   CitizenReport.ai_label != CitizenReport.hazard_type)


def report_overview():
    status = _count_by(CitizenReport.status)
    return {'pending': status.get('submitted', 0), 'accepted': status.get('accepted', 0),
            'rejected': status.get('rejected', 0), 'total': sum(status.values()),
            'ai_analyzed': CitizenReport.query.filter_by(ai_status='completed').count(),
            'ai_disagree': CitizenReport.query.filter(ai_disagreement()).count()}


def push_overview():
    return {'total': PushSubscription.query.count(),
            'enabled': PushSubscription.query.filter_by(enabled=True).count(),
            'disabled': PushSubscription.query.filter_by(enabled=False).count(),
            'failing': PushSubscription.query.filter(PushSubscription.enabled.is_(True),
                                                     PushSubscription.failure_count > 0).count(),
            'users': db.session.query(db.func.count(db.distinct(PushSubscription.user_id)))
            .filter(PushSubscription.enabled.is_(True)).scalar(),
            'push_users': _push_users().count(),
            'configured': emergency_dispatcher.push_configured()}


def system_health():
    """Timestamps and counters only: no configuration values, keys or request data."""
    emergency = Notification.query.filter(Notification.type.in_(emergency_dispatcher.ALERT_TYPES),
                                          Notification.severity.in_(emergency_severities())) \
        .order_by(Notification.created_at.desc(), Notification.id.desc()).first()
    revision = None
    if db.inspect(db.engine).has_table('alembic_version'):
        revision = db.session.execute(db.text('SELECT version_num FROM alembic_version')).scalar()
    since = datetime.utcnow() - timedelta(hours=24)
    return {
        'latest_reading': SensorReading.query.order_by(SensorReading.received_at.desc(),
                                                       SensorReading.id.desc()).first(),
        'latest_hazard': Incident.query.order_by(Incident.detected_at.desc(), Incident.id.desc()).first(),
        'latest_emergency': emergency,
        'runtime': dict(RUNTIME),
        'push_configured': emergency_dispatcher.push_configured(),
        'schema_revision': revision,
        'audit_failures_24h': AuditLog.query.filter(AuditLog.success.is_(False), AuditLog.created_at >= since).count(),
        'readings_24h': SensorReading.query.filter(SensorReading.received_at >= since).count(),
    }


def dashboard():
    return {**overview(), 'users': user_counts(), 'iot': iot_summary(), 'hazards': hazard_overview(),
            'reports': report_overview(), 'push': push_overview(), 'health': system_health(),
            'unread': Notification.query.filter_by(is_read=False).count(),
            'recent_audit': AuditLog.query.order_by(AuditLog.id.desc()).limit(6).all()}


def users_overview():
    return {'counts': user_counts(), 'admins': User.query.filter_by(role='admin').order_by(User.username).all()}


# --- IoT devices --------------------------------------------------------------

def devices(district_id=None, q=None, status=None, sensor_type=None, page=1):
    query = IoTDevice.query
    if district_id:
        query = query.filter(IoTDevice.district_id == district_id)
    if status in DEVICE_STATES:
        query = query.filter(_state_filter(status, datetime.utcnow()))
    if sensor_type:
        query = query.filter(IoTDevice.id.in_(db.session.query(SensorReading.device_id)
                                              .filter(SensorReading.sensor_type == sensor_type)))
    condition = _search([IoTDevice.name, IoTDevice.device_id], q)
    if condition is not None:
        query = query.filter(condition)
    return query.order_by(IoTDevice.name, IoTDevice.id).paginate(page=page, per_page=PER_PAGE, error_out=False)


def sensor_types():
    return [t for (t,) in db.session.query(SensorReading.sensor_type).distinct().order_by(SensorReading.sensor_type)]


def device_states(device_list):
    now = datetime.utcnow()
    return {d.id: device_state(d, now) for d in device_list}


TELEMETRY_WINDOWS = (1, 6, 24, 168)  # hours offered by the telemetry filter


def device_detail(device, sensor_type=None, hours=None, page=1):
    now = datetime.utcnow()
    query = SensorReading.query.filter(SensorReading.device_id == device.id)
    if sensor_type:
        query = query.filter(SensorReading.sensor_type == sensor_type)
    if hours in TELEMETRY_WINDOWS:
        query = query.filter(SensorReading.received_at >= now - timedelta(hours=hours))
    state = device_state(device, now)
    last_toggle = AuditLog.query.filter(AuditLog.target_type == 'device', AuditLog.target_id == str(device.id),
                                        AuditLog.action.in_(('DISABLED_DEVICE', 'ENABLED_DEVICE')),
                                        AuditLog.success.is_(True)).order_by(AuditLog.id.desc()).first()
    return {
        'state': state, 'age': freshness(device.last_seen, now)[1],
        'readings': query.order_by(SensorReading.received_at.desc(), SensorReading.id.desc())
        .paginate(page=page, per_page=50, error_out=False),
        'sensor_types': [t for (t,) in db.session.query(SensorReading.sensor_type)
                         .filter(SensorReading.device_id == device.id).distinct().order_by(SensorReading.sensor_type)],
        'latest': latest_readings([device.id]).get(device.id, []),
        'disabled_by_admin': last_toggle if state == 'disabled' and last_toggle
        and last_toggle.action == 'DISABLED_DEVICE' else None,
        'audit': audit_for('device', [device.id]),
    }


# --- hazards ------------------------------------------------------------------

HAZARD_STATUS_FILTERS = ('active',) + tuple(HAZARD_STATUS)


def hazards(district_id=None, q=None, status=None, event_type=None, severity=None, page=1):
    query = Incident.query
    if status == 'active':
        query = query.filter(Incident.status.in_(ACTIVE_STATUSES))
    elif status in HAZARD_STATUS:
        query = query.filter(Incident.status == status)
    if event_type in HAZARD_TYPES:
        query = query.filter(Incident.event_type == event_type)
    if severity in HAZARD_SEVERITY:
        query = query.filter(Incident.severity == severity)
    if district_id:
        query = query.filter(hazard_event_service.affects_district(district_id))
    condition = _search([Incident.title, Incident.location], q)
    if condition is not None:
        query = query.filter(condition)
    pagination = query.order_by(Incident.updated_at.desc(), Incident.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)
    ids = [h.id for h in pagination.items]
    rows = {i: {'photos': 0, 'notified': 0, 'last_notified': None} for i in ids}
    if ids:
        for incident_id, n in db.session.query(CitizenReport.incident_id, db.func.count()) \
                .filter(CitizenReport.incident_id.in_(ids)).group_by(CitizenReport.incident_id):
            rows[incident_id]['photos'] = n
        for incident_id, n, last in db.session.query(Notification.incident_id, db.func.count(),
                                                     db.func.max(Notification.created_at)) \
                .filter(Notification.incident_id.in_(ids)).group_by(Notification.incident_id):
            rows[incident_id].update(notified=n, last_notified=last)
    return pagination, rows


def hazard_detail(incident):
    notifications = db.session.query(Notification.type, Notification.severity, db.func.count(),
                                     db.func.sum(db.case((Notification.is_read.is_(False), 1), else_=0)),
                                     db.func.max(Notification.created_at)) \
        .filter(Notification.incident_id == incident.id) \
        .group_by(Notification.type, Notification.severity).order_by(db.func.max(Notification.created_at)).all()
    return {
        'history': IncidentStatusHistory.query.filter_by(incident_id=incident.id)
        .order_by(IncidentStatusHistory.created_at, IncidentStatusHistory.id).all(),
        'reports': CitizenReport.query.filter_by(incident_id=incident.id).order_by(CitizenReport.created_at.desc()).all(),
        'notifications': [{'type': t, 'severity': s, 'recipients': n, 'unread': unread or 0, 'at': at,
                           'emergency': emergency_dispatcher.is_emergency(t, s),
                           'pushed': emergency_dispatcher.pushable(t, s)} for t, s, n, unread, at in notifications],
        'transitions': VALID_STATUS_TRANSITIONS.get(incident.status, []),
        'open_actions': IncidentResponseAction.query.filter(
            IncidentResponseAction.incident_id == incident.id,
            IncidentResponseAction.status.in_(('planned', 'in_progress'))).count(),
        'audit': audit_for('hazard', [incident.id]),
    }


# --- citizen reports ----------------------------------------------------------

REPORT_AI_FILTERS = tuple(AI_STATUS) + ('disagree',)


def reports(district_id=None, q=None, status=None, hazard_type=None, ai=None, page=1):
    query = CitizenReport.query.join(User, CitizenReport.reporter_id == User.id)
    if district_id:
        query = query.filter(CitizenReport.district_id == district_id)
    if status in REPORT_STATUS:
        query = query.filter(CitizenReport.status == status)
    if hazard_type in VISUAL_HAZARD_TYPES:
        query = query.filter(CitizenReport.hazard_type == hazard_type)
    if ai == 'disagree':
        query = query.filter(ai_disagreement())
    elif ai in AI_STATUS:
        query = query.filter(CitizenReport.ai_status == ai)
    condition = _search([User.username, CitizenReport.location], q)
    if condition is not None:
        query = query.filter(condition)
    return query.order_by(CitizenReport.created_at.desc(), CitizenReport.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)


# --- Web Push -----------------------------------------------------------------

SUBSCRIPTION_STATUSES = ('enabled', 'disabled', 'failing')


def subscriptions(q=None, status=None, page=1):
    """Metadata only (owner, browser, state, failures). Endpoint and keys are never rendered."""
    query = PushSubscription.query.join(User, PushSubscription.user_id == User.id)
    if status == 'enabled':
        query = query.filter(PushSubscription.enabled.is_(True))
    elif status == 'disabled':
        query = query.filter(PushSubscription.enabled.is_(False))
    elif status == 'failing':
        query = query.filter(PushSubscription.failure_count > 0)
    condition = _search([User.username], q)
    if condition is not None:
        query = query.filter(condition)
    return query.order_by(PushSubscription.updated_at.desc(), PushSubscription.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)


def recent_push_failures(limit=10):
    return PushSubscription.query.filter(PushSubscription.failure_count > 0) \
        .order_by(PushSubscription.updated_at.desc()).limit(limit).all()


# --- audit log ----------------------------------------------------------------

AUDIT_OUTCOMES = ('success', 'failure')


def audit_entries(q=None, action=None, target_type=None, outcome=None, page=1):
    query = AuditLog.query
    if action in AUDIT_ACTIONS:
        query = query.filter(AuditLog.action == action)
    if target_type in AUDIT_TARGETS:
        query = query.filter(AuditLog.target_type == target_type)
    if outcome in AUDIT_OUTCOMES:
        query = query.filter(AuditLog.success.is_(outcome == 'success'))
    condition = _search([AuditLog.actor_username, AuditLog.target_label, AuditLog.reason], q)
    if condition is not None:
        query = query.filter(condition)
    return query.order_by(AuditLog.id.desc()).paginate(page=page, per_page=50, error_out=False)


def record(actor, action, target_type, target_id, label, reason, summary, success=True):
    """Add one audit row to the session (the caller commits). Never pass credentials in label/summary."""
    db.session.add(AuditLog(actor_id=actor.id, actor_username=actor.username, actor_role=actor.role,
                            action=action, target_type=target_type, target_id=str(target_id),
                            target_label=(label or '')[:200], reason=reason[:REASON_MAX],
                            summary=(summary or '')[:500], success=success))
    current_app.logger.info('admin_action admin=%s action=%s target=%s:%s success=%s',
                            actor.id, action, target_type, target_id, success)


# --- actions: mutate, return a safe summary; the route audits and commits -----

def _require_managed(admin, user):
    """Citizen and authority accounts only. Admin accounts (including your own) are not managed here."""
    if user.role not in ('citizen', 'authority') or user.id == admin.id:
        raise PermissionError('Only citizen and authority accounts can be managed here.')


def set_active(admin, user, active):
    _require_managed(admin, user)
    if bool(user.is_active) == bool(active):
        raise ValueError(f'@{user.username} is already {"enabled" if active else "disabled"}.')
    user.is_active = bool(active)
    if not active:
        user.end_sessions()  # also stops an old session reviving if the account is enabled again
        return f'{user.role} account @{user.username} disabled; sessions ended; records preserved'
    return f'{user.role} account @{user.username} enabled'


def reset_password(admin, user, temporary, confirm):
    """Set a temporary password (stored only as a hash) that must be changed at next login.
    The existing password is never readable: only its one-way hash exists."""
    _require_managed(admin, user)
    if temporary != confirm:
        raise ValueError('Temporary passwords do not match.')
    if len(temporary or '') < account_service.MIN_PASSWORD:
        raise ValueError('Temporary password must be at least 8 characters.')
    user.set_password(temporary)
    user.must_change_password = True
    user.end_sessions()
    return f'temporary password set for @{user.username}; must change at next login; sessions ended'


def force_password_change(admin, user):
    _require_managed(admin, user)
    if user.must_change_password:
        raise ValueError(f'@{user.username} must already change their password.')
    user.must_change_password = True
    return f'@{user.username} must change their password before doing anything else'


def terminate_sessions(admin, user):
    _require_managed(admin, user)
    user.end_sessions()
    return f'all sessions of @{user.username} ended'


def set_authority_active(admin, authority, active):
    """Deactivate/reactivate an authority = every linked account. Nothing is deleted: hazards, reports,
    response records and devices stay; devices keep reporting unless disabled separately."""
    accounts = User.query.filter_by(authority_id=authority.id, role='authority').all()
    if not accounts:
        raise ValueError('No account is linked to this authority.')
    changed = [u for u in accounts if bool(u.is_active) != bool(active)]
    if not changed:
        raise ValueError(f'All linked accounts are already {"enabled" if active else "disabled"}.')
    for user in changed:
        user.is_active = bool(active)
        if not active:
            user.end_sessions()
    names = ', '.join(f'@{u.username}' for u in changed)
    return f'{len(changed)} linked account(s) {"enabled" if active else "disabled; sessions ended"}: {names}'


def set_device_enabled(admin, device, enabled):
    if bool(device.enabled) == bool(enabled):
        raise ValueError(f'{device.device_id} is already {"enabled" if enabled else "disabled"}.')
    device.enabled = bool(enabled)
    if enabled:
        return f'{device.device_id}: authenticated telemetry accepted again'
    return f'{device.device_id}: authenticated telemetry refused (the physical ESP32 is not switched off)'


def rotate_device_key(admin, device):
    """Returns (plaintext key, summary). Only the hash is stored; the old key stops working at commit."""
    api_key = IoTDevice.generate_api_key()
    device.api_key_hash = IoTDevice.hash_api_key(api_key)
    return api_key, f'{device.device_id}: API key rotated; previous key invalid'


# One-time display of a freshly rotated key (Post/Redirect/Get). The plaintext lives only here, in
# process memory, until the redirected GET takes it or it expires: never in the DB, the session
# cookie, a URL, browser storage or a log. The session only carries a random lookup token.
# ponytail: per-process store; fine for the single-process server (run.py). Behind several workers
# the redirected GET could land elsewhere and the key would be lost (rotate again): use a shared
# short-lived cache (e.g. Redis with TTL) then.
ONE_TIME_KEY_SECONDS = 300
_one_time_keys = {}
_one_time_lock = threading.Lock()


def stash_one_time_key(admin_id, device_pk, api_key):
    token = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _one_time_lock:
        for stale in [t for t, v in _one_time_keys.items() if v[3] <= now]:
            del _one_time_keys[stale]
        _one_time_keys[token] = (admin_id, device_pk, api_key, now + ONE_TIME_KEY_SECONDS)
    return token


def take_one_time_key(token, admin_id, device_pk):
    """The key once, for the admin who rotated it and that device only; None otherwise."""
    with _one_time_lock:
        entry = _one_time_keys.pop(token, None) if token else None
    if entry and entry[:2] == (admin_id, device_pk) and entry[3] > time.monotonic():
        return entry[2]
    return None


def change_hazard_status(admin, incident, new_status, reason):
    """Exceptional intervention through the normal lifecycle (valid transitions only, history row,
    lifecycle notifications). Commits via hazard_event_service."""
    if new_status not in VALID_STATUS_TRANSITIONS.get(incident.status, []):
        raise ValueError(f'Invalid transition from {incident.status} to {new_status}.')
    old = hazard_event_service.transition_event_status(incident, new_status, actor_id=admin.id,
                                                       note=f'Super Admin intervention: {reason}')
    return f'hazard #{incident.id} status {old} -> {new_status}'


def review_report(admin, report, status):
    """Accept/reject through the M05 review path (original evidence untouched). Commits."""
    if not citizen_report_service.can_review(admin, report):
        raise PermissionError('You cannot review your own report.')
    citizen_report_service.review_report(admin, report, status)
    return f'report #{report.id} {status}'


def disable_subscription(admin, subscription):
    if not subscription.enabled:
        raise ValueError('This subscription is already disabled.')
    subscription.enabled = False
    return f'push subscription #{subscription.id} of @{subscription.user.username} disabled'
