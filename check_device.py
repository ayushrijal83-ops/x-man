from app import create_app
from app.models import IoTDevice, SensorReading, Incident, Notification, User, District
from app.extensions import db
from datetime import datetime, timedelta
import json

app = create_app()
with app.app_context():
    device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').first()
    if not device:
        print('Device ESP32-SEISMIC-001 not found')
    else:
        print(f'Device: {device.device_id}, ID: {device.id}, District: {device.district_id}, Enabled: {device.enabled}, Status: {device.status}')
        print(f'Location: {device.location_description}, Lat: {device.latitude}, Lon: {device.longitude}')
        print(f'Kind: {device.kind}')
        district = District.query.get(device.district_id)
        dname = district.name if district else 'Unknown'
        print(f'District: {dname}')