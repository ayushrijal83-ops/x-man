"""Tests for device management endpoints and security."""
import pytest
import json
from app.extensions import db
from app.models import IoTDevice, SensorReading, District, Authority, River
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
            name='Test Water Authority',
            category='water',
            district_id=district_id,
        )
        db.session.add(authority)
        db.session.flush()
        db.session.commit()
        return authority.id


def _make_user(app, district_id, authority_id=None, role='authority', username='test_auth'):
    with app.app_context():
        user = User(
            username=username,
            email=f'{username}@test.np',
            role=role,
            district_id=district_id,
            authority_id=authority_id,
        )
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        return user.id


def _login_client(client, username='test_auth', password='password'):
    """Helper to log in a user."""
    return client.post('/auth/authority/login', data={
        'username': username,
        'password': password,
    })


class TestDeviceManagement:
    """Tests for device management endpoints."""

    def test_register_device_as_authority(self, app, client):
        """Test authority can register a device."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        _login_client(client)

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-REG-001',
            'name': 'Registered Sensor',
            'district_id': district_id,
            'latitude': 27.5,
            'longitude': 85.5,
            'firmware_version': '1.0.0',
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['status'] == 'created'
        assert 'device' in data
        assert data['device']['device_id'] == 'ESP32-REG-001'
        assert 'api_key' in data['device']
        assert 'warning' in data

        with app.app_context():
            device = IoTDevice.query.filter_by(device_id='ESP32-REG-001').first()
            assert device is not None
            assert device.authority_id == authority_id

    def test_register_device_as_admin(self, app, client):
        """Test admin can register a device with authority_id."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id=None, role='admin', username='admin_user')

        # Need to login as admin - but auth doesn't have admin login
        # Let's use the authority login and set role=admin in session
        with app.app_context():
            user = User.query.filter_by(username='admin_user').first()
            user.role = 'admin'
            db.session.commit()

        _login_client(client, username='admin_user')

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-ADMIN-001',
            'name': 'Admin Sensor',
            'district_id': district_id,
            'authority_id': authority_id,
        })

        assert response.status_code == 201

    def test_register_device_missing_fields(self, app, client):
        """Test registration fails with missing required fields."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        _login_client(client)

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-INCOMPLETE',
            # missing name and district_id
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'required' in data['error'].lower()

    def test_register_duplicate_device_id(self, app, client):
        """Test registration fails with duplicate device_id."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        _login_client(client)

        client.post('/api/iot/devices', json={
            'device_id': 'ESP32-DUPLICATE-REG',
            'name': 'Sensor 1',
            'district_id': district_id,
        })

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-DUPLICATE-REG',
            'name': 'Sensor 2',
            'district_id': district_id,
        })

        assert response.status_code == 409

    def test_register_device_invalid_district(self, app, client):
        """Test registration fails with invalid district_id."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        _login_client(client)

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-BAD-DISTRICT',
            'name': 'Bad District Sensor',
            'district_id': 99999,
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'district' in data['error'].lower()

    def test_list_devices_as_authority(self, app, client):
        """Test authority can list their devices."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        user_id = _make_user(app, district_id, authority_id)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-LIST-001',
                name='Listed Sensor',
                district_id=district_id,
                authority_id=authority_id,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()

        _login_client(client)

        response = client.get('/api/iot/devices')

        assert response.status_code == 200
        data = response.get_json()
        assert 'devices' in data
        assert len(data['devices']) >= 1
        assert data['devices'][0]['device_id'] == 'ESP32-LIST-001'

    def test_list_devices_as_citizen_forbidden(self, app, client):
        """Test citizen cannot list devices."""
        district_id = _make_district(app)
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_user')

        client.post('/auth/login', data={'username': 'citizen_user', 'password': 'password'})

        response = client.get('/api/iot/devices')

        assert response.status_code == 403

    def test_update_device_enabled(self, app, client):
        """Test authority can update device enabled status."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-UPDATE-001',
                name='Updatable Sensor',
                district_id=district_id,
                authority_id=authority_id,
                enabled=True,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()
            device_id = device.id

        _login_client(client)

        response = client.patch(f'/api/iot/devices/{device_id}', json={
            'enabled': False,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['enabled'] is False

    def test_update_device_status(self, app, client):
        """Test authority can update device status."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-STATUS-UPDATE',
                name='Status Sensor',
                district_id=district_id,
                authority_id=authority_id,
                status='active',
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()
            device_id = device.id

        _login_client(client)

        response = client.patch(f'/api/iot/devices/{device_id}', json={
            'status': 'maintenance',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['device']['status'] == 'maintenance'

    def test_rotate_device_key(self, app, client):
        """Test authority can rotate device API key."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-ROTATE-001',
                name='Rotate Sensor',
                district_id=district_id,
                authority_id=authority_id,
            )
            device.api_key_hash = IoTDevice.hash_api_key('old-key')
            db.session.add(device)
            db.session.commit()
            device_id = device.id

        _login_client(client)

        response = client.post(f'/api/iot/devices/{device_id}/rotate-key')

        assert response.status_code == 200
        data = response.get_json()
        assert 'api_key' in data
        assert data['api_key'] != 'old-key'

        # Verify new key works
        headers = {'Authorization': f'Bearer ESP32-ROTATE-001:{data["api_key"]}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })
        assert response.status_code == 201

    def test_authority_cannot_access_other_devices(self, app, client):
        """Test authority cannot update devices from other authorities."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        # Create another authority and device
        authority_id_2 = _make_authority(app, district_id)
        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-OTHER-AUTH',
                name='Other Authority Sensor',
                district_id=district_id,
                authority_id=authority_id_2,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()
            other_device_id = device.id

        _login_client(client)

        response = client.patch(f'/api/iot/devices/{other_device_id}', json={
            'enabled': False,
        })

        assert response.status_code == 403


class TestSecurity:
    """Security-focused tests."""

    def test_citizen_cannot_register_device(self, app, client):
        """Test citizen cannot register device."""
        district_id = _make_district(app)
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_user')

        client.post('/auth/login', data={'username': 'citizen_user', 'password': 'password'})

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-CITIZEN-REG',
            'name': 'Citizen Sensor',
            'district_id': district_id,
        })

        assert response.status_code == 403

    def test_citizen_cannot_list_devices(self, app, client):
        """Test citizen cannot list devices."""
        district_id = _make_district(app)
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_user2')

        client.post('/auth/login', data={'username': 'citizen_user2', 'password': 'password'})

        response = client.get('/api/iot/devices')

        assert response.status_code == 403

    def test_citizen_cannot_update_device(self, app, client):
        """Test citizen cannot update device."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-SEC-001',
                name='Sec Sensor',
                district_id=district_id,
                authority_id=authority_id,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.commit()
            device_id = device.id

        # Login as different citizen
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_user3')
        client.post('/auth/login', data={'username': 'citizen_user3', 'password': 'password'})

        response = client.patch(f'/api/iot/devices/{device_id}', json={
            'enabled': False,
        })

        assert response.status_code == 403

    def test_unauthenticated_request_rejected(self, app, client):
        """Test unauthenticated requests are rejected."""
        response = client.get('/api/iot/devices')
        assert response.status_code == 401

        response = client.post('/api/iot/devices', json={})
        assert response.status_code == 401

        response = client.get('/api/iot/latest')
        assert response.status_code == 401

    def test_disabled_device_rejected(self, app, client):
        """Test disabled device cannot send telemetry."""
        district_id = _make_district(app)

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-DISABLED-SEC',
                name='Disabled Security Sensor',
                district_id=district_id,
                enabled=False,
            )
            device.api_key_hash = IoTDevice.hash_api_key('disabled-key')
            db.session.add(device)
            db.session.commit()

        headers = {'Authorization': 'Bearer ESP32-DISABLED-SEC:disabled-key'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]
        })

        assert response.status_code == 401

    def test_api_key_not_in_response_after_creation(self, app, client):
        """Test API key is only returned once on creation."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id)

        _login_client(client)

        response = client.post('/api/iot/devices', json={
            'device_id': 'ESP32-KEY-ONCE',
            'name': 'Key Once Sensor',
            'district_id': district_id,
        })

        assert response.status_code == 201
        data = response.get_json()
        assert 'api_key' in data['device']

        # List devices should not include API keys
        response = client.get('/api/iot/devices')
        data = response.get_json()
        for device in data['devices']:
            if device['device_id'] == 'ESP32-KEY-ONCE':
                assert 'api_key' not in device


class TestLatestEndpoint:
    """Tests for GET /api/iot/latest endpoint."""

    def test_latest_telemetry_authenticated(self, app, client):
        """Test authenticated user can get latest telemetry."""
        district_id = _make_district(app)
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_latest')

        client.post('/auth/login', data={'username': 'citizen_latest', 'password': 'password'})

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-LATEST-001',
                name='Latest Sensor',
                district_id=district_id,
                enabled=True,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.flush()

            reading = SensorReading(
                device_id=device.id,
                sensor_type='water_level',
                value=2.5,
                unit='m',
            )
            db.session.add(reading)
            db.session.commit()

        response = client.get('/api/iot/latest')

        assert response.status_code == 200
        data = response.get_json()
        assert 'readings' in data
        assert len(data['readings']) == 1
        assert data['readings'][0]['sensor_type'] == 'water_level'
        assert data['readings'][0]['value'] == 2.5

    def test_latest_telemetry_filter_by_sensor_type(self, app, client):
        """Test filtering latest telemetry by sensor type."""
        district_id = _make_district(app)
        _make_user(app, district_id, authority_id=None, role='citizen', username='citizen_latest2')

        client.post('/auth/login', data={'username': 'citizen_latest2', 'password': 'password'})

        with app.app_context():
            device = IoTDevice(
                device_id='ESP32-LATEST-002',
                name='Latest Sensor 2',
                district_id=district_id,
                enabled=True,
            )
            device.api_key_hash = IoTDevice.hash_api_key('key')
            db.session.add(device)
            db.session.flush()

            for stype, value in [('water_level', 2.0), ('temperature', 25.0), ('humidity', 60.0)]:
                reading = SensorReading(
                    device_id=device.id,
                    sensor_type=stype,
                    value=value,
                    unit='m' if stype == 'water_level' else ('°C' if stype == 'temperature' else '%'),
                )
                db.session.add(reading)
            db.session.commit()

        response = client.get('/api/iot/latest?sensor_type=water_level')

        assert response.status_code == 200
        data = response.get_json()
        assert len(data['readings']) == 1
        assert data['readings'][0]['sensor_type'] == 'water_level'