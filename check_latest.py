from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from app.services import risk_service
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    
    # Get the latest high readings (last burst)
    threshold = 85
    readings = SensorReading.query.filter_by(
        device_id=device.id,
        sensor_type='vibration'
    ).order_by(SensorReading.recorded_at.desc()).all()
    
    # Find the latest burst of readings >= 85 mg
    high_readings = [r for r in readings if r.value >= threshold and r.quality == 'good']
    
    if high_readings:
        # Sort by recorded_at ascending
        high_readings_sorted = sorted(high_readings, key=lambda r: r.recorded_at)
        
        # Find the latest cluster - readings within 60 seconds of each other
        # Start from the end and work backwards
        latest_burst = []
        for r in reversed(high_readings_sorted):
            if not latest_burst:
                latest_burst.append(r)
            else:
                # Check if this reading is within 60s of the first in the burst
                if (latest_burst[0].recorded_at - r.recorded_at).total_seconds() <= 60:
                    latest_burst.insert(0, r)
                else:
                    break
        
        print(f'Latest burst: {len(latest_burst)} readings')
        for r in latest_burst:
            print(f'  {r.recorded_at} | {r.value} mg')
        
        print(f'\nBurst window: {latest_burst[0].recorded_at} -> {latest_burst[-1].recorded_at}')
        print(f'Peak in burst: {max(r.value for r in latest_burst)} mg')
        
        # Now manually evaluate the risk for this device at the end of this burst
        # Simulate what evaluate_motion would do
        since = latest_burst[-1].recorded_at  # use the end of the burst as "now"
        vib_readings = [r for r in readings if r.sensor_type == 'vibration' and r.recorded_at >= since - timedelta(seconds=60)]
        tilt_readings = [r for r in readings if r.sensor_type == 'tilt' and r.recorded_at >= since - timedelta(seconds=60)]
        
        print(f'\nVibration readings in 60s window ending at {since}: {len(vib_readings)}')
        for r in vib_readings:
            print(f'  {r.recorded_at} | {r.value} mg | quality={r.quality}')
        
        # Call the actual motion_assessment
        assessment = risk_service.motion_assessment(device, now=since)
        print(f'\nRisk Assessment at {since}:')
        print(f'  Hazard type: {assessment.hazard_type}')
        print(f'  Level: {assessment.level}')
        print(f'  Action: {assessment.action}')
        print(f'  Severity: {assessment.severity}')
        print(f'  Action warranted: {assessment.action_warranted}')
        print(f'  Reasons: {assessment.reasons}')
        print(f'  Evidence: {assessment.evidence}')
        print(f'  Sources: {assessment.sources}')
        print(f'  District ID: {assessment.district_id}')
        
        # Also check at the current time (latest reading)
        now = datetime.utcnow()
        assessment_now = risk_service.motion_assessment(device, now=now)
        print(f'\nRisk Assessment at now ({now}):')
        print(f'  Level: {assessment_now.level}')
        print(f'  Action: {assessment_now.action}')
        print(f'  Action warranted: {assessment_now.action_warranted}')
        print(f'  Reasons: {assessment_now.reasons}')
        print(f'  Evidence: {assessment_now.evidence}')
EOF