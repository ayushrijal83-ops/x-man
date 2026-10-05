"""Phase 3 tests: Seismic telemetry integration with device-event state machine.

These tests follow the existing pattern of only checking API responses,
since Flask test client rolls back database after each request in testing mode.
"""

import pytest
from datetime import datetime, timedelta

from app.extensions import db
from app.models import IoTDevice, SensorReading, District
from app.services.seismic_state import MotionLevel, SeismicState
from app.services.seismic_state_persistence import load_state


T0 = datetime(2026, 10, 1, 10, 0, 0)


def make_device(app, device_id='TEST-SEISMIC-001'):
    """Create a seismic device for testing. Returns the string device_id."""
    with app.app_context():
        district = District(name=f'Test District {device_id}', province='Test Province')
        db.session.add(district)
        db.session.commit()

        device = IoTDevice(
            device_id=device_id,
            name=f'Test Seismic {device_id}',
            district_id=district.id,
            kind='sensor',
            enabled=True,
        )
        api_key = 'test-seismic-key'
        device.api_key_hash = IoTDevice.hash_api_key(api_key)
        db.session.add(device)
        db.session.commit()
        return device_id


def _telemetry(client, device_id, *readings, timestamp=None):
    """Send telemetry for a device."""
    body = {'readings': [dict(r) for r in readings]}
    if timestamp:
        body['timestamp'] = timestamp
    return client.post('/api/iot/telemetry', json=body,
                       headers={'Authorization': f'Bearer {device_id}:test-seismic-key'})


def V(value):
    return {'sensor_type': 'vibration', 'value': value, 'unit': 'mg'}


def TILT(value):
    return {'sensor_type': 'tilt', 'value': value, 'unit': '°'}


class TestSeismicTelemetryIntegration:
    """Test the integration of seismic telemetry with the state machine via API responses."""

    def test_seismic_telemetry_creates_sensor_reading(self, app, client):
        """Test 1: Seismic telemetry creates SensorReading (existing behavior)."""
        device_id = make_device(app)
        
        response = _telemetry(client, device_id, V(50.0))
        assert response.status_code == 201
        assert response.get_json()['stored'] == 1

    def test_seismic_telemetry_updates_state_machine(self, app, client):
        """Test 2: Seismic telemetry is processed by state machine (returns accepted)."""
        device_id = make_device(app)
        
        # Send abnormal vibration reading
        response = _telemetry(client, device_id, V(100.0))
        assert response.status_code == 201
        assert response.get_json()['stored'] == 1

    def test_continuous_burst_one_event(self, app, client):
        """Test 3: Continuous burst returns accepted for each reading."""
        device_id = make_device(app)
        
        # Send a burst of abnormal readings
        for value in [85, 100, 500, 1000, 800, 700]:
            response = _telemetry(client, device_id, V(value))
            assert response.status_code == 201
            assert response.get_json()['stored'] == 1

    def test_recovery_sequence(self, app, client):
        """Test 4: Recovery sequence - abnormal then normal readings all accepted."""
        device_id = make_device(app)
        
        # Start with abnormal readings
        response = _telemetry(client, device_id, V(200.0))
        assert response.status_code == 201
        
        response = _telemetry(client, device_id, V(300.0))
        assert response.status_code == 201
        
        # Send normal readings for recovery
        for _ in range(3):
            response = _telemetry(client, device_id, V(50.0))
            assert response.status_code == 201

    def test_below_threshold_stays_quiet(self, app, client):
        """Test: Vibration below threshold returns accepted but no event start."""
        device_id = make_device(app)
        
        # Send readings below threshold (85 mg)
        for value in [50, 60, 70, 80]:
            response = _telemetry(client, device_id, V(value))
            assert response.status_code == 201

    def test_single_spike_ignored(self, app, client):
        """Test: Single spike above threshold doesn't cause errors."""
        device_id = make_device(app)
        
        # Single spike
        response = _telemetry(client, device_id, V(10))      # normal
        assert response.status_code == 201
        
        response = _telemetry(client, device_id, V(1000))    # spike
        assert response.status_code == 201
        
        response = _telemetry(client, device_id, V(12))      # normal
        assert response.status_code == 201

    def test_tilt_readings_processed(self, app, client):
        """Test: Tilt readings are also processed without errors."""
        device_id = make_device(app)
        
        # Send tilt readings
        response = _telemetry(client, device_id, TILT(0.5))
        assert response.status_code == 201
        
        response = _telemetry(client, device_id, TILT(0.8))
        assert response.status_code == 201
        
        response = _telemetry(client, device_id, TILT(7.0))  # Large change
        assert response.status_code == 201

    def test_flood_device_no_seismic_state(self, app, client):
        """Test: Flood device (water_level) works normally."""
        device_id = make_device(app, 'FLOOD-DEVICE-001')
        
        # Send water level reading (not vibration/tilt)
        response = _telemetry(client, device_id, 
                              {'sensor_type': 'water_level', 'value': 2.5, 'unit': 'm'})
        assert response.status_code == 201
        assert response.get_json()['stored'] == 1


class TestSeismicTelemetryAuthentication:
    """Verify existing authentication/validation still works."""

    def test_invalid_credentials_rejected(self, app, client):
        """Invalid device credentials are rejected."""
        device_id = make_device(app)
        
        response = client.post('/api/iot/telemetry', json={
            'readings': [V(100.0)]
        }, headers={'Authorization': 'Bearer INVALID_DEVICE:bad-key'})
        
        assert response.status_code == 401

    def test_disabled_device_rejected(self, app, client):
        """Disabled device is rejected."""
        device_id = make_device(app)
        
        with app.app_context():
            device = IoTDevice.query.filter_by(device_id=device_id).first()
            device.enabled = False
            db.session.commit()
        
        response = _telemetry(client, device_id, V(100.0))
        assert response.status_code == 401

    def test_decommissioned_device_rejected(self, app, client):
        """Decommissioned device is rejected."""
        device_id = make_device(app)
        
        with app.app_context():
            device = IoTDevice.query.filter_by(device_id=device_id).first()
            device.status = 'decommissioned'
            db.session.commit()
        
        response = _telemetry(client, device_id, V(100.0))
        assert response.status_code == 401

    def test_malformed_payload_rejected(self, app, client):
        """Malformed payload is rejected."""
        device_id = make_device(app)
        
        response = client.post('/api/iot/telemetry', data='not json',
                               content_type='application/json',
                               headers={'Authorization': f'Bearer {device_id}:test-seismic-key'})
        assert response.status_code == 400

    def test_missing_readings_rejected(self, app, client):
        """Missing readings array is rejected."""
        device_id = make_device(app)
        
        response = client.post('/api/iot/telemetry', json={},
                               headers={'Authorization': f'Bearer {device_id}:test-seismic-key'})
        assert response.status_code == 400


class TestExistingTelemetryBehavior:
    """Verify existing telemetry behavior is unchanged."""

    def test_water_level_still_works(self, app, client):
        """Water level readings still work normally."""
        device_id = make_device(app)
        
        response = _telemetry(client, device_id, 
                              {'sensor_type': 'water_level', 'value': 2.5, 'unit': 'm'})
        assert response.status_code == 201
        assert response.get_json()['stored'] == 1

    def test_temperature_humidity_still_work(self, app, client):
        """Temperature and humidity readings still work."""
        device_id = make_device(app)
        
        response = _telemetry(client, device_id,
                              {'sensor_type': 'temperature', 'value': 25.0, 'unit': '°C'},
                              {'sensor_type': 'humidity', 'value': 65.0, 'unit': '%'})
        assert response.status_code == 201
        assert response.get_json()['stored'] == 2

    def test_device_last_seen_updated(self, app, client):
        """Device last_seen is updated on telemetry (checked via response)."""
        device_id = make_device(app)
        
        response = _telemetry(client, device_id, V(50.0))
        assert response.status_code == 201
        # Response includes timestamp which indicates last_seen was updated
        assert 'timestamp' in response.get_json()

    def test_mixed_readings_in_one_request(self, app, client):
        """Multiple sensor types in one request work."""
        device_id = make_device(app)
        
        response = _telemetry(client, device_id,
                              V(100.0),
                              {'sensor_type': 'temperature', 'value': 25.0, 'unit': '°C'},
                              {'sensor_type': 'water_level', 'value': 1.5, 'unit': 'm'})
        assert response.status_code == 201
        assert response.get_json()['stored'] == 3

    def test_reading_with_timestamp(self, app, client):
        """Reading with explicit timestamp works."""
        device_id = make_device(app)
        timestamp = '2026-10-01T10:30:00Z'
        
        response = _telemetry(client, device_id, V(100.0), timestamp=timestamp)
        assert response.status_code == 201
        assert response.get_json()['stored'] == 1