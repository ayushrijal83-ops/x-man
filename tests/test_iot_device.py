"""Tests for IoT Device model and authentication."""
import pytest
from app.extensions import db
from app.models import IoTDevice, SensorReading, District, Authority
from app.models.user import User


def _make_district(app):
    with app.app_context():
        district = District(name='Test District', province='Test Province')
        db.session.add(district)
        db.session.commit()
        return district.id


def _make_authority(app, district_id):
    with app.app_context():
        authority = Authority(
            name='Test Authority',
            category='water',
            district_id=district_id,
        )
        db.session.add(authority)
        db.session.commit()
        return authority.id


def _make_user(app, district_id, authority_id=None, role='authority'):
    with app.app_context():
        user = User(
            username='test_auth',
            email='auth@test.np',
            role=role,
            district_id=district_id,
            authority_id=authority_id,
        )
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        return user.id


class TestIoTDeviceModel:
    """Tests for IoTDevice model."""

    def test_device_creation(self, app):
        """Test basic device creation."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-TEST-001',
                name='Test Sensor',
                district_id=district_id,
            )
            api_key = IoTDevice.generate_api_key()
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

            assert device.id is not None
            assert device.device_id == 'ESP32-TEST-001'
            assert device.enabled is True
            assert device.status == 'active'

    def test_unique_device_id(self, app):
        """Test device_id must be unique."""
        district_id = _make_district(app)

        with app.app_context():
            device1 = IoTDevice(
                device_id='ESP32-DUPLICATE',
                name='Sensor 1',
                district_id=district_id,
            )
            device1.api_key_hash = IoTDevice.hash_api_key('key1')
            db.session.add(device1)
            db.session.commit()

            device2 = IoTDevice(
                device_id='ESP32-DUPLICATE',
                name='Sensor 2',
                district_id=district_id,
            )
            device2.api_key_hash = IoTDevice.hash_api_key('key2')
            db.session.add(device2)

            with pytest.raises(Exception):
                db.session.commit()

    def test_api_key_generation(self, app):
        """Test API key generation and hashing."""
        district_id = _make_district(app)

        with app.app_context():
            api_key = IoTDevice.generate_api_key()
            assert len(api_key) > 20

            hash1 = IoTDevice.hash_api_key(api_key)
            hash2 = IoTDevice.hash_api_key(api_key)
            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex

    def test_api_key_verification(self, app):
        """Test API key verification."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-VERIFY-001',
                name='Verify Sensor',
                district_id=district_id,
            )
            api_key = 'test-api-key-12345'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

            assert device.verify_api_key(api_key) is True
            assert device.verify_api_key('wrong-key') is False

    def test_device_enabled_flag(self, app):
        """Test device enabled/disabled flag."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-ENABLED-001',
                name='Enabled Sensor',
                district_id=district_id,
                enabled=True,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()

            assert device.enabled is True

            device.enabled = False
            db.session.commit()

            assert device.enabled is False

    def test_device_status_values(self, app):
        """Test device status field accepts valid values."""
        district_id = _make_district(app)

        with app.app_context():
            for status in ['active', 'inactive', 'maintenance', 'decommissioned']:
                device = IoTDevice(
                    device_id=f'ESP32-STATUS-{status}',
                    name=f'{status} Sensor',
                    district_id=district_id,
                    status=status,
                )
                device.api_key_hash = IoTDevice.hash_api_key('key')
                db.session.add(device)

            db.session.commit()

    def test_device_to_dict(self, app):
        """Test device to_dict method."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-DICT-001',
                name='Dict Sensor',
                district_id=district_id,
                description='Test description',
                latitude=27.5,
                longitude=85.5,
                firmware_version='1.0.0',
            )
            api_key = 'test-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

            d = device.to_dict()
            assert d['device_id'] == 'ESP32-DICT-001'
            assert d['name'] == 'Dict Sensor'
            assert d['description'] == 'Test description'
            assert d['latitude'] == 27.5
            assert 'api_key' not in d

            d_with_key = device.to_dict(include_api_key=True)
            assert '_plain_api_key' not in d_with_key  # Not set


class TestSensorReadingModel:
    """Tests for SensorReading model."""

    def test_reading_creation(self, app):
        """Test basic sensor reading creation."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-READING-001',
                name='Reading Sensor',
                district_id=district_id,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()

            reading = SensorReading(
                device_id=device.id,
                sensor_type='water_level',
                value=2.5,
                unit='m',
            )
            db.session.add(reading)
            db.session.commit()

            assert reading.id is not None
            assert reading.sensor_type == 'water_level'
            assert reading.value == 2.5
            assert reading.unit == 'm'
            assert reading.quality == 'good'

    def test_reading_to_dict(self, app):
        """Test reading to_dict method."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-READING-DICT',
                name='Dict Reading Sensor',
                district_id=district_id,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()

            reading = SensorReading(
                device_id=device.id,
                sensor_type='temperature',
                value=25.5,
                unit='°C',
            )
            db.session.add(reading)
            db.session.commit()

            d = reading.to_dict()
            assert d['sensor_type'] == 'temperature'
            assert d['value'] == 25.5
            assert d['unit'] == '°C'
            assert 'recorded_at' in d


class TestDeviceAuthentication:
    """Tests for device authentication mechanism."""

    def test_authenticate_valid_device(self, app, client):
        """Test authentication with valid device credentials."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-AUTH-001',
                name='Auth Sensor',
                district_id=district_id,
                enabled=True,
            )
            api_key = 'valid-api-key-123'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

        # Test via Authorization header
        headers = {'Authorization': f'Bearer ESP32-AUTH-001:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 201

    def test_authenticate_invalid_api_key(self, app, client):
        """Test authentication fails with wrong API key."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-AUTH-002',
                name='Auth Sensor 2',
                district_id=district_id,
                enabled=True,
            )
            device.api_key_hash = IoTDevice.hash_api_key('correct-key')
            db.session.add(device)
            db.session.commit()

        headers = {'Authorization': 'Bearer ESP32-AUTH-002:wrong-key'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 401

    def test_authenticate_disabled_device(self, app, client):
        """Test authentication fails for disabled device."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-AUTH-003',
                name='Disabled Sensor',
                district_id=district_id,
                enabled=False,
            )
            api_key = 'disabled-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

        headers = {'Authorization': f'Bearer ESP32-AUTH-003:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 401

    def test_authenticate_nonexistent_device(self, app, client):
        """Test authentication fails for non-existent device."""
        headers = {'Authorization': 'Bearer ESP32-NONEXISTENT:some-key'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 401

    def test_authenticate_missing_credentials(self, app, client):
        """Test authentication fails with missing credentials."""
        response = client.post('/api/iot/telemetry', json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 401