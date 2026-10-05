from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    
    # Find all notifications for incident 4
    incident = db.session.get(Incident, 4)
    notifications = Notification.query.filter_by(incident_id=4).order_by(Notification.created_at.desc()).all()
    
    print(f'Notifications for incident 4: {len(notifications)}')
    for n in notifications:
        user = db.session.get(User, n.user_id)
        print(f'  ID: {n.id} | Type: {n.type} | Severity: {n.severity} | User: {n.user_id} ({user.username if user else "N/A"}) | Read: {n.is_read} | Created: {n.created_at}')
        print(f'    Title: {n.title}')
        print(f'    Message: {n.message}')
        print(f'    Dedup key: {n.dedup_key}')
        print()
    
    # Check all notifications for user_id=3 (ram)
    user3 = db.session.get(User, 3)
    print(f'User 3: {user3.username if user3 else "Not found"}, District: {user3.district_id if user3 else "N/A"}')
    
    user3_notifications = Notification.query.filter_by(user_id=3).order_by(Notification.created_at.desc()).all()
    print(f'\nAll notifications for user 3: {len(user3_notifications)}')
    for n in user3_notifications:
        inc = db.session.get(Incident, n.incident_id) if n.incident_id else None
        print(f'  ID: {n.id} | Type: {n.type} | Severity: {n.severity} | Incident: {n.incident_id} ({inc.event_type if inc else "N/A"}) | Read: {n.is_read} | Created: {n.created_at}')
        print(f'    Title: {n.title}')
        print()
EOF