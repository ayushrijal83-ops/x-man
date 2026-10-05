from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    
    # Find all earthquake incidents for this district
    incidents = Incident.query.filter_by(
        event_type='earthquake',
        district_id=device.district_id
    ).order_by(Incident.detected_at.desc()).all()
    
    print(f'Earthquake incidents for district {device.district_id}: {len(incidents)}')
    
    for inc in incidents:
        print(f'  ID: {inc.id} | Status: {inc.status} | Severity: {inc.severity} | Source: {inc.source} | Detected: {inc.detected_at} | Updated: {inc.updated_at}')
        print(f'    Title: {inc.title}')
        print(f'    Description: {inc.description}')
        print(f'    Source Ref: {inc.source_reference}')
        print(f'    Coords: {inc.latitude}, {inc.longitude}')
        print(f'    River: {inc.river_id}, Road: {inc.road_segment_id}')
        print()
    
    # Also check all incidents for this district
    all_incidents = Incident.query.filter_by(district_id=device.district_id).order_by(Incident.detected_at.desc()).all()
    print(f'All incidents for district {device.district_id}: {len(all_incidents)}')
    
    for inc in all_incidents:
        print(f'  ID: {inc.id} | Type: {inc.event_type} | Status: {inc.status} | Severity: {inc.severity} | Source: {inc.source} | Detected: {inc.detected_at}')
EOF