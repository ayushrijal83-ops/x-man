from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    
    # Get all vibration readings for this device
    readings = SensorReading.query.filter_by(
        device_id=device.id,
        sensor_type='vibration'
    ).order_by(SensorReading.received_at.desc()).all()
    
    print(f'Total vibration readings: {len(readings)}')
    
    # Show the latest 50 readings
    for r in readings[:50]:
        print(f'  {r.received_at} | {r.value} mg | quality={r.quality} | recorded_at={r.recorded_at}')
    
    # Find the latest burst where vibration >= 85 mg
    threshold = 85
    high_readings = [r for r in readings if r.value >= threshold and r.quality == 'good']
    print(f'\nReadings >= {threshold} mg (good quality): {len(high_readings)}')
    
    if high_readings:
        # Find the time window of the latest burst
        # Sort by recorded_at
        high_readings_sorted = sorted(high_readings, key=lambda r: r.recorded_at)
        print(f'First high reading: {high_readings_sorted[0].recorded_at} | {high_readings_sorted[0].value} mg')
        print(f'Last high reading: {high_readings_sorted[-1].recorded_at} | {high_readings_sorted[-1].value} mg')
        
        # Check for consecutive readings (within 60 second window)
        window = timedelta(seconds=60)
        for i, r in enumerate(high_readings_sorted):
            window_readings = [hr for hr in high_readings_sorted if hr.recorded_at >= r.recorded_at and hr.recorded_at <= r.recorded_at + window]
            if len(window_readings) >= 3:
                print(f'\nFound {len(window_readings)} readings in 60s window starting at {r.recorded_at}:')
                for wr in window_readings:
                    print(f'  {wr.recorded_at} | {wr.value} mg')
                break
        
        peak = max(high_readings_sorted, key=lambda r: r.value)
        print(f'\nPeak vibration: {peak.value} mg at {peak.recorded_at}')
EOF