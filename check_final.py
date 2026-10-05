from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from app.services import risk_service
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    # Check current config
    from flask import current_app
    print(f'EMERGENCY_MIN_SEVERITY: {current_app.config.get("EMERGENCY_MIN_SEVERITY")}')
    print(f'MOTION_VIBRATION_THRESHOLD_MG: {current_app.config.get("MOTION_VIBRATION_THRESHOLD_MG")}')
    print(f'MOTION_TILT_CHANGE_THRESHOLD_DEG: {current_app.config.get("MOTION_TILT_CHANGE_THRESHOLD_DEG")}')
    
    # Check incident 4 details
    inc = db.session.get(Incident, 4)
    print(f'\nIncident 4:')
    print(f'  report_count: {inc.report_count}')
    print(f'  status: {inc.status}')
    print(f'  severity: {inc.severity}')
    print(f'  detected_at: {inc.detected_at}')
    print(f'  updated_at: {inc.updated_at}')
    
    # Check if there are any notifications created after the burst
    # Burst ended ~03:11:24, incident updated ~03:11:48
    notifs = Notification.query.filter(
        Notification.incident_id == 4,
        Notification.created_at >= datetime(2026, 10, 5, 3, 10, 0)
    ).all()
    print(f'\nNotifications for incident 4 after 03:10: {len(notifs)}')
    for n in notifs:
        print(f'  ID: {n.id} | Type: {n.type} | Created: {n.created_at} | Read: {n.is_read}')
    
    # Check user 3's push subscription
    user3 = db.session.get(User, 3)
    print(f'\nUser 3 (ram):')
    print(f'  emergency_alert_state: {user3.emergency_alert_state}')
    print(f'  emergency_sound_enabled: {user3.emergency_sound_enabled}')
    print(f'  push_subscriptions: {user3.push_subscriptions.filter_by(enabled=True).count()}')
    
    # Check what /api/emergency/active would return
    from app.services.emergency_dispatcher import is_emergency, ALERT_TYPES
    from app.models.incident import ACTIVE_STATUSES
    since = datetime.utcnow() - timedelta(hours=48)
    rows = Notification.query.join(Incident, Notification.incident_id == Incident.id).filter(
        Notification.user_id == 3, Notification.is_read.is_(False),
        Notification.created_at >= since, Notification.type.in_(ALERT_TYPES),
        Incident.status.in_(ACTIVE_STATUSES)) \
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(20).all()
    
    print(f'\n/api/emergency/active query results for user 3: {len(rows)}')
    for n in rows:
        print(f'  ID: {n.id} | Type: {n.type} | Severity: {n.severity} | Emergency: {is_emergency(n.type, n.severity)} | Read: {n.is_read}')
EOF