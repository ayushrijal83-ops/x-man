"""Disaster Monitoring Dashboard (M07): read-only, role-scoped aggregation.

Presentation only. Nothing here detects hazards, scores risk, changes state or
sends notifications: it reads what M01–M06 already decided. Visibility rules are
the existing ones:
  hazards       -- public to any logged-in user (as /api/hazards); citizens and
                   authorities are scoped to their district, admins see all
  devices       -- authority: devices owned by its authority (as /api/iot/devices); admin: all
  reports + AI  -- citizen_report_service.visible_reports_query (M05), managers only (M06)
  notifications -- the user's own (M03)
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import CitizenReport, District, Incident, IncidentAffectedDistrict, IoTDevice, Notification
from app.models.citizen_report import AI_STATUS, REPORT_STATUS
from app.models.incident_response import IncidentInvestigation, IncidentResponseAction
from app.models.incident import ACTIVE_STATUSES, HAZARD_SEVERITY, HAZARD_TYPES
from app.models.iot_device import SensorReading
from app.services import citizen_report_service, notification_service
from app.services.hazard_event_service import affects_district, get_event_statistics

# Device freshness is a UI label computed at read time from last_seen. It never
# changes IoTDevice.status (an operator setting) or anything else in the database.
ONLINE_SECONDS = 5 * 60
STALE_SECONDS = 60 * 60
MAX_HAZARDS = 200
MAX_REPORTS = 20
MAX_NOTIFICATIONS = 10

ALL = object()  # scope sentinel: no district filter


def is_manager(user):
    return user.role in ('authority', 'admin')


def district_scope(user, requested_district_id=None):
    """District the dashboard shows for `user`: an id, ALL, or None (nothing operational).

    Only admins may pick another district. Raises PermissionError otherwise.
    """
    if user.role == 'admin':
        return requested_district_id or ALL
    if user.role == 'authority':
        own = user.authority.district_id if user.authority else None
    else:
        own = user.district_id
    if requested_district_id and requested_district_id != own:
        raise PermissionError('Not authorized for this district')
    if own is None:
        # a citizen without a home district sees the public nationwide picture;
        # an authority not linked to an authority sees nothing operational
        return ALL if user.role == 'citizen' else None
    return own


def _hazard_filter(scope):
    filters = [Incident.status.in_(ACTIVE_STATUSES)]
    if scope is not ALL:
        filters.append(affects_district(scope))
    return filters


def active_hazards(scope):
    if scope is None:
        return []
    return Incident.query.filter(*_hazard_filter(scope)).options(
        joinedload(Incident.district), joinedload(Incident.river), joinedload(Incident.road_segment),
        selectinload(Incident.additional_districts).joinedload(IncidentAffectedDistrict.district),
    ).order_by(Incident.updated_at.desc(), Incident.id.desc()).limit(MAX_HAZARDS).all()


def hazard_summary(scope):
    """Counts of active hazards by type and by severity, straight from Incident rows."""
    by_type = dict.fromkeys(HAZARD_TYPES, 0)
    by_severity = dict.fromkeys(HAZARD_SEVERITY, 0)
    if scope is not None:
        rows = db.session.query(Incident.event_type, Incident.severity, db.func.count(Incident.id)) \
            .filter(*_hazard_filter(scope)).group_by(Incident.event_type, Incident.severity).all()
        for event_type, severity, count in rows:
            if event_type in by_type:
                by_type[event_type] += count
            if severity in by_severity:
                by_severity[severity] += count
    return {'total': sum(by_type.values()), 'by_type': by_type, 'by_severity': by_severity}


def freshness(last_seen, now):
    """'online' (<= 5 min), 'stale' (<= 60 min), 'offline' (older) or 'never' — presentation only."""
    if last_seen is None:
        return 'never', None
    age = max(0, int((now - last_seen).total_seconds()))
    label = 'online' if age <= ONLINE_SECONDS else 'stale' if age <= STALE_SECONDS else 'offline'
    return label, age


def visible_devices(user, admin_district_id=None):
    if user.role == 'admin':
        query = IoTDevice.query
        if admin_district_id:
            query = query.filter(IoTDevice.district_id == admin_district_id)
    elif user.role == 'authority' and user.authority_id:
        query = IoTDevice.query.filter(IoTDevice.authority_id == user.authority_id)
    else:
        return []
    return query.options(joinedload(IoTDevice.district), joinedload(IoTDevice.river)) \
        .order_by(IoTDevice.name, IoTDevice.id).all()


def latest_readings(device_ids):
    """{device pk: [latest reading per sensor_type]} in two queries, whatever the device count."""
    if not device_ids:
        return {}
    newest = db.session.query(db.func.max(SensorReading.id)) \
        .filter(SensorReading.device_id.in_(device_ids)) \
        .group_by(SensorReading.device_id, SensorReading.sensor_type)
    readings = SensorReading.query.filter(SensorReading.id.in_(newest)) \
        .order_by(SensorReading.device_id, SensorReading.sensor_type).all()
    grouped = {}
    for r in readings:
        grouped.setdefault(r.device_id, []).append({
            'sensor_type': r.sensor_type, 'value': r.value, 'unit': r.unit, 'quality': r.quality,
            'recorded_at': r.recorded_at.isoformat() if r.recorded_at else None,
            'received_at': r.received_at.isoformat() if r.received_at else None,
        })
    return grouped


def device_payload(devices, now):
    readings = latest_readings([d.id for d in devices])
    items = []
    for d in devices:
        label, age = freshness(d.last_seen, now)
        items.append({
            'id': d.id,
            'device_id': d.device_id,
            'name': d.name,
            'district': {'id': d.district.id, 'name': d.district.name} if d.district else None,
            'river_name': d.river.name if d.river else None,
            'location_description': d.location_description,
            'latitude': d.latitude,
            'longitude': d.longitude,
            'status': d.status,
            'enabled': bool(d.enabled),
            'last_seen': d.last_seen.isoformat() if d.last_seen else None,
            'freshness': label,
            'seconds_since_seen': age,
            'readings': readings.get(d.id, []),
        })
    return items


def recent_reports(user, admin_district_id=None):
    """Managers only: the M05 visibility query, with M06 AI evidence. No description, filename or reporter."""
    if not is_manager(user):
        return []
    query = citizen_report_service.visible_reports_query(user)
    if admin_district_id:
        query = query.filter(CitizenReport.district_id == admin_district_id)
    reports = query \
        .options(joinedload(CitizenReport.district), joinedload(CitizenReport.incident)) \
        .order_by(CitizenReport.created_at.desc(), CitizenReport.id.desc()).limit(MAX_REPORTS).all()
    return [{
        'id': r.id,
        'hazard_type': r.hazard_type,
        'district': {'id': r.district.id, 'name': r.district.name} if r.district else None,
        'location': r.location,
        'created_at': r.created_at.isoformat() if r.created_at else None,
        'status': r.status,
        'incident_id': r.incident_id,
        'incident_status': r.incident.status if r.incident else None,
        'ai_analysis': r.ai_dict(),
    } for r in reports]


def response_summaries(incident_ids):
    """M09 investigation/response state per hazard for managers: counts only, two GROUP BYs."""
    if not incident_ids:
        return {}
    result = {i: {'notes': 0, 'open_actions': 0, 'actions': 0} for i in incident_ids}
    for incident_id, count in db.session.query(IncidentInvestigation.incident_id, db.func.count()) \
            .filter(IncidentInvestigation.incident_id.in_(incident_ids)).group_by(IncidentInvestigation.incident_id):
        result[incident_id]['notes'] = count
    for incident_id, status, count in db.session.query(IncidentResponseAction.incident_id,
                                                       IncidentResponseAction.status, db.func.count()) \
            .filter(IncidentResponseAction.incident_id.in_(incident_ids)) \
            .group_by(IncidentResponseAction.incident_id, IncidentResponseAction.status):
        result[incident_id]['actions'] += count
        if status in ('planned', 'in_progress'):
            result[incident_id]['open_actions'] += count
    return result


def admin_statistics(now):
    """System-wide counts for admins (never district-filtered): events (M02 service), reports,
    notification activity."""
    def counts(column, keys, *filters):
        rows = dict(db.session.query(column, db.func.count()).filter(*filters).group_by(column).all())
        return {k: rows.get(k, 0) for k in keys}

    since = now - timedelta(hours=24)
    return {
        'events': get_event_statistics(),
        'reports_by_status': counts(CitizenReport.status, REPORT_STATUS),
        'reports_by_ai_status': counts(CitizenReport.ai_status, AI_STATUS),
        'notifications_last_24h': db.session.query(db.func.count(Notification.id))
        .filter(Notification.created_at >= since).scalar(),
        'devices_total': IoTDevice.query.count(),
    }


def build(user, requested_district_id=None):
    """The whole dashboard payload for one user. Raises PermissionError / LookupError."""
    if requested_district_id and not db.session.get(District, requested_district_id):
        raise LookupError('District not found')
    scope = district_scope(user, requested_district_id)
    now = datetime.utcnow()
    scope_district = db.session.get(District, scope) if isinstance(scope, int) else None
    hazards = active_hazards(scope)
    payload = {
        'role': user.role,
        'generated_at': now.isoformat() + 'Z',
        'scope': {'district': {'id': scope_district.id, 'name': scope_district.name} if scope_district else None,
                  'nationwide': scope is ALL},
        'summary': hazard_summary(scope),
        'hazards': [h.to_dict(include_internal=False) for h in hazards],
        'notifications': [n.to_dict() for n in
                          notification_service.get_user_notifications(user.id, limit=MAX_NOTIFICATIONS)],
        'unread_notifications': notification_service.unread_count(user.id),
    }
    if is_manager(user):
        summaries = response_summaries([h.id for h in hazards])
        for item in payload['hazards']:
            item['response'] = summaries.get(item['id'], {'notes': 0, 'open_actions': 0, 'actions': 0})
            item['response_url'] = f"/hazards/{item['id']}/response"
        admin_district_id = requested_district_id if user.role == 'admin' else None
        payload['devices'] = device_payload(visible_devices(user, admin_district_id), now)
        payload['reports'] = recent_reports(user, admin_district_id)
        payload['freshness_rule'] = {'online_seconds': ONLINE_SECONDS, 'stale_seconds': STALE_SECONDS}
    if user.role == 'admin':
        payload['statistics'] = admin_statistics(now)
    return payload


def authority_operations(user):
    """Operational view for the authority panel (product-quality milestone).

    Same scope rules as the monitoring dashboard: an authority sees hazards affecting its
    authority's district, devices its authority owns, and reports per the M05 visibility query.
    """
    scope = district_scope(user)
    now = datetime.utcnow()
    hazards = active_hazards(scope)
    by_status = {}
    for h in hazards:
        by_status[h.status] = by_status.get(h.status, 0) + 1
    devices = device_payload(visible_devices(user), now)
    reports = recent_reports(user)
    open_actions = []
    if hazards:
        open_actions = IncidentResponseAction.query.filter(
            IncidentResponseAction.incident_id.in_([h.id for h in hazards]),
            IncidentResponseAction.status.in_(['planned', 'in_progress']),
        ).options(joinedload(IncidentResponseAction.author)) \
            .order_by(IncidentResponseAction.created_at.desc()).limit(10).all()
    pending_reports = citizen_report_service.visible_reports_query(user) \
        .filter(CitizenReport.status == 'submitted').count() if is_manager(user) else 0
    points = [{'id': h.id, 'type': h.event_type, 'severity': h.severity, 'status': h.status,
               'title': h.title or h.event_type, 'lat': h.latitude, 'lon': h.longitude}
              for h in hazards if h.latitude is not None and h.longitude is not None]
    return {
        'hazards': hazards,
        'summary': hazard_summary(scope),
        'by_status': by_status,
        'needs_investigation': by_status.get('detected', 0),
        'response': response_summaries([h.id for h in hazards]),
        'devices': devices,
        'device_freshness': {label: sum(1 for d in devices if d['freshness'] == label)
                             for label in ('online', 'stale', 'offline', 'never')},
        'reports': reports,
        'pending_reports': pending_reports,
        'open_actions': open_actions,
        'map_points': points,
    }
