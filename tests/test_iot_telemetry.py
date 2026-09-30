"""Tests for telemetry ingestion endpoint."""
import pytest
import json
from app.extensions import db
from app.models import IoTDevice, SensorReading, District, River
from datetime import datetime


class TestTelemetryIngestion:
    """Tests for POST /api/iot/telemetry endpoint."""

    def _setup_device(self, app, device_id='ESP32-TELEMETRY-001'):
        """Helper to create district and device, returns (district_id, device_id, api_key)."""
        with app.app_context():
            district = District(name='Test District', province='Test Province')
            db.session.add(district)
            db.session.commit()
            district_id = district.id

            device = IoTDevice(
                device_id=device_id,
                name='Telemetry Sensor',
                district_id=district_id,
                enabled=True,
            )
            api_key = 'test-telemetry-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()
            return district_id, device.device_id, api_key

    def _setup_river(self, app, district_id, name='Test River', current_level=2.0, danger_level=4.0, status='normal'):
        """Helper to create a river."""
        with app.app_context():
            river = River(
                name=name,
                district_id=district_id,
                current_level=current_level,
                danger_level=danger_level,
                status=status,
            )
            db.session.add(river)
            db.session.commit()
            return river.id

    def test_valid_single_reading(self, app, client):
        """Test ingesting a single valid reading."""
        district_id, device_id, api_key = self._setup_device(app)

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [
                {'sensor_type': 'water_level', 'value': 2.35, 'unit': 'm'}
            ]
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['status'] == 'accepted'
        assert data['stored'] == 1

        with app.app_context():
            readings = SensorReading.query.all()
            assert len(readings) == 1
            assert readings[0].sensor_type == 'water_level'
            assert readings[0].value == 2.35
            assert readings[0].unit == 'm'

    def test_valid_multiple_readings(self, app, client):
        """Test ingesting multiple readings in one request."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-MULTI-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [
                {'sensor_type': 'water_level', 'value': 2.35, 'unit': 'm'},
                {'sensor_type': 'temperature', 'value': 25.5, 'unit': '°C'},
                {'sensor_type': 'humidity', 'value': 65.0, 'unit': '%'},
            ]
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['stored'] == 3

        with app.app_context():
            readings = SensorReading.query.all()
            assert len(readings) == 3
            types = {r.sensor_type for r in readings}
            assert types == {'water_level', 'temperature', 'humidity'}

    def test_reading_with_timestamp(self, app, client):
        """Test ingesting reading with explicit timestamp."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-TS-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        timestamp = '2024-01-15T10:30:00Z'
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'timestamp': timestamp,
            'readings': [
                {'sensor_type': 'water_level', 'value': 2.0, 'unit': 'm'}
            ]
        })

        assert response.status_code == 201
        with app.app_context():
            reading = SensorReading.query.first()
            assert reading.recorded_at is not None

    def test_missing_readings_array(self, app, client):
        """Test error when readings array is missing."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-MISSING-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={})

        assert response.status_code == 400
        data = response.get_json()
        assert 'readings' in data['error'].lower()

    def test_empty_readings_array(self, app, client):
        """Test error when readings array is empty."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-EMPTY-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': []
        })

        assert response.status_code == 400

    def test_missing_sensor_type(self, app, client):
        """Test error when sensor_type is missing."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-NO-TYPE-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'value': 2.0, 'unit': 'm'}]
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'sensor_type' in data['details'][0]

    def test_missing_value(self, app, client):
        """Test error when value is missing."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-NO-VAL-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'unit': 'm'}]
        })

        assert response.status_code == 400

    def test_missing_unit(self, app, client):
        """Test error when unit is missing."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-NO-UNIT-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 2.0}]
        })

        assert response.status_code == 400

    def test_invalid_value_type(self, app, client):
        """Test error when value is not a number."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-BAD-VAL-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 'not-a-number', 'unit': 'm'}]
        })

        assert response.status_code == 400

    def test_unsupported_sensor_type(self, app, client):
        """Test error for unsupported sensor type."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-BAD-TYPE-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'unsupported_sensor', 'value': 1.0, 'unit': 'x'}]
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'unsupported' in data['details'][0].lower()

    def test_invalid_unit_for_sensor(self, app, client):
        """Test error for wrong unit for sensor type."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-BAD-UNIT-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 2.0, 'unit': '°C'}]
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'unit' in data['details'][0].lower()

    def test_value_out_of_range(self, app, client):
        """Test error for value out of expected range."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-RANGE-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'temperature', 'value': 200, 'unit': '°C'}]
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'range' in data['details'][0].lower()

    def test_too_many_readings(self, app, client):
        """Test error when too many readings in one request."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-MANY-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        readings = [{'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'} for _ in range(51)]
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': readings
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'too many' in data['error'].lower()

    def test_partial_valid_readings(self, app, client):
        """Test that valid readings are stored even if some are invalid."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-PARTIAL-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [
                {'sensor_type': 'water_level', 'value': 2.0, 'unit': 'm'},
                {'sensor_type': 'water_level', 'unit': 'm'},
                {'sensor_type': 'temperature', 'value': 25.0, 'unit': '°C'},
            ]
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['stored'] == 2
        assert 'warnings' in data

    def test_malformed_json(self, app, client):
        """Test error for malformed JSON."""
        district_id, device_id, api_key = self._setup_device(app, 'ESP32-MALFORMED-001')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers,
                               data='not json', content_type='application/json')

        assert response.status_code == 400