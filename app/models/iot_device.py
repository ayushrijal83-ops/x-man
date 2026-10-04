from app.extensions import db
from datetime import datetime
import hashlib
import hmac
import secrets

# M-LIVE-02: what a device is allowed to do. Set once at provisioning; never a normal edit.
#   sensor       ESP32 telemetry (water_level, vibration, tilt, ...)
#   camera_node  mobile field node: field evidence uploads (+ battery heartbeat telemetry)
DEVICE_KINDS = ('sensor', 'camera_node')


class IoTDevice(db.Model):
    """IoT device model for hardware sensors (ESP32, etc.)."""
    __tablename__ = 'iot_devices'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'), nullable=True)
    river_id = db.Column(db.Integer, db.ForeignKey('rivers.id'), nullable=True)
    kind = db.Column(db.String(20), nullable=False, default='sensor', server_default='sensor')  # DEVICE_KINDS
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_description = db.Column(db.String(200))
    firmware_version = db.Column(db.String(50))
    api_key_hash = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, inactive, maintenance, decommissioned
    enabled = db.Column(db.Boolean, default=True)
    last_seen = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    district = db.relationship('District', backref='iot_devices')
    authority = db.relationship('Authority', backref='iot_devices')
    river = db.relationship('River', backref='iot_devices')

    def __repr__(self):
        return f'<IoTDevice {self.device_id}>'

    @staticmethod
    def generate_api_key():
        """Generate a new API key for a device."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_api_key(api_key):
        """Hash an API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def verify_api_key(self, api_key):
        """Verify an API key against the stored hash."""
        return hmac.compare_digest(self.api_key_hash or '', self.hash_api_key(api_key))

    def to_dict(self, include_api_key=False):
        """Convert to dictionary."""
        data = {
            'id': self.id,
            'device_id': self.device_id,
            'name': self.name,
            'description': self.description,
            'district_id': self.district_id,
            'district_name': self.district.name if self.district else None,
            'authority_id': self.authority_id,
            'authority_name': self.authority.name if self.authority else None,
            'river_id': self.river_id,
            'river_name': self.river.name if self.river else None,
            'kind': self.kind,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'location_description': self.location_description,
            'firmware_version': self.firmware_version,
            'status': self.status,
            'enabled': self.enabled,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_api_key:
            data['api_key'] = getattr(self, '_plain_api_key', None)
        return data


class SensorReading(db.Model):
    """Sensor reading/telemetry model for IoT devices."""
    __tablename__ = 'sensor_readings'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('iot_devices.id'), nullable=False, index=True)
    sensor_type = db.Column(db.String(50), nullable=False, index=True)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    quality = db.Column(db.String(20), default='good')  # good, suspect, bad
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    raw_payload = db.Column(db.Text)

    device = db.relationship('IoTDevice', backref='readings')

    __table_args__ = (
        db.Index('ix_sensor_readings_device_time', 'device_id', 'recorded_at'),
        db.Index('ix_sensor_readings_type_time', 'sensor_type', 'recorded_at'),
    )

    def __repr__(self):
        return f'<SensorReading {self.sensor_type}={self.value} {self.unit} from Device {self.device_id}>'

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'sensor_type': self.sensor_type,
            'value': self.value,
            'unit': self.unit,
            'quality': self.quality,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }