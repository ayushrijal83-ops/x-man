from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    
    # Get all tilt readings for this device
    readings = SensorReading.query.filter_by(
        device_id=device.id,
        sensor_type='tilt'
    ).order_by(SensorReading.received_at.desc()).all()
    
    print(f'Total tilt readings: {len(readings)}')
    
    # Show the latest 50 readings
    for r in readings[:50]:
        print(f'  {r.received_at} | {r.value} deg | quality={r.quality} | recorded_at={r.recorded_at}')
    
    # Find readings with high tilt change
    high_readings = [r for r in readings if r.quality == 'good']
    print(f'\nGood quality tilt readings: {len(high_readings)}')
EOF