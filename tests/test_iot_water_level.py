"""Tests for water level sensor integration and risk engine."""
import pytest
from app.extensions import db
from app.models import IoTDevice, SensorReading, District, River
from app.services.risk_engine import (
    compute_river_status,
    compute_river_risk_level,
    assess_water_level_risk,
    validate_sensor_reading,
    SENSOR_TYPES,
)


class TestRiverStatusComputation:
    """Tests for river status computation logic.

    Matches the original level_status() from seed_nepal_data.py:
    - 'normal' for < 80% of danger level
    - 'rising' for 80-100% of danger level
    - 'flooding' for >= 100% of danger level
    - 'unknown' for None/invalid levels
    """

    def test_normal_status(self):
        """Test normal status when below 80% of danger level."""
        assert compute_river_status(1.0, 4.0) == 'normal'
        assert compute_river_status(2.0, 4.0) == 'normal'
        assert compute_river_status(2.3, 4.0) == 'normal'
        assert compute_river_status(3.0, 4.0) == 'normal'   # 75% -> normal
        assert compute_river_status(3.1, 4.0) == 'normal'   # 77.5% -> normal

    def test_rising_status(self):
        """Test rising status at 80-100% of danger level."""
        assert compute_river_status(3.2, 4.0) == 'rising'
        assert compute_river_status(3.5, 4.0) == 'rising'
        assert compute_river_status(3.9, 4.0) == 'rising'

    def test_flooding_status(self):
        """Test flooding status at or above danger level."""
        assert compute_river_status(4.0, 4.0) == 'flooding'
        assert compute_river_status(4.5, 4.0) == 'flooding'
        assert compute_river_status(5.0, 4.0) == 'flooding'

    def test_unknown_when_none(self):
        """Test unknown status when levels are None."""
        assert compute_river_status(None, 4.0) == 'unknown'
        assert compute_river_status(2.0, None) == 'unknown'
        assert compute_river_status(None, None) == 'unknown'

    def test_unknown_when_zero_danger(self):
        """Test unknown status when danger level is zero."""
        assert compute_river_status(2.0, 0) == 'unknown'
        assert compute_river_status(2.0, -1) == 'unknown'

    def test_risk_level_computation(self):
        """Test numeric risk level computation.

        Risk levels: 0=unknown, 1=normal, 2=rising, 3=flooding
        """
        result = compute_river_risk_level(1.0, 4.0)
        assert result['level'] == 1
        assert result['label'] == 'Normal'
        assert result['percentage'] == 25.0

        result = compute_river_risk_level(3.2, 4.0)
        assert result['level'] == 2
        assert result['label'] == 'Rising'
        assert result['percentage'] == 80.0

        result = compute_river_risk_level(4.5, 4.0)
        assert result['level'] == 3
        assert result['label'] == 'Flooding'
        assert result['percentage'] == 112.5

        result = compute_river_risk_level(None, 4.0)
        assert result['level'] == 0
        assert result['label'] == 'Unknown'
        assert result['percentage'] is None


class TestWaterLevelRiskAssessment:
    """Tests for water level risk assessment."""

    def test_normal_risk(self):
        """Test normal risk assessment."""
        result = assess_water_level_risk(1.0, 4.0)
        assert result['status'] == 'normal'
        assert result['risk_level'] == 1
        assert result['alert_required'] is False

    def test_high_risk(self):
        """Test risk assessment at 60-80% (still normal status, no alert)."""
        result = assess_water_level_risk(2.5, 4.0)
        assert result['status'] == 'normal'
        assert result['risk_level'] == 1
        assert result['alert_required'] is False

    def test_rising_alert_required(self):
        """Test rising status triggers alert (risk_level >= 2)."""
        result = assess_water_level_risk(3.5, 4.0)
        assert result['status'] == 'rising'
        assert result['risk_level'] == 2
        assert result['alert_required'] is True

    def test_flooding_alert_required(self):
        """Test flooding status triggers alert."""
        result = assess_water_level_risk(4.5, 4.0)
        assert result['status'] == 'flooding'
        assert result['risk_level'] == 3
        assert result['alert_required'] is True

    def test_suspect_quality_no_alert(self):
        """Test suspect quality suppresses alert."""
        result = assess_water_level_risk(4.5, 4.0, sensor_quality='suspect')
        assert result['alert_required'] is False

    def test_bad_quality_no_alert(self):
        """Test bad quality suppresses alert."""
        result = assess_water_level_risk(4.5, 4.0, sensor_quality='bad')
        assert result['alert_required'] is False
        assert result['status'] == 'unknown'

    def test_reason_generation(self):
        """Test reason string generation."""
        result = assess_water_level_risk(3.2, 4.0)
        assert '80%' in result['reason'] or '80.0%' in result['reason']


class TestSensorValidation:
    """Tests for sensor reading validation."""

    def test_valid_water_level(self):
        valid, error = validate_sensor_reading('water_level', 2.5, 'm')
        assert valid is True
        assert error is None

    def test_valid_temperature(self):
        valid, error = validate_sensor_reading('temperature', 25.0, '°C')
        assert valid is True

    def test_valid_humidity(self):
        valid, error = validate_sensor_reading('humidity', 65.0, '%')
        assert valid is True

    def test_valid_rainfall(self):
        valid, error = validate_sensor_reading('rainfall', 10.0, 'mm')
        assert valid is True

    def test_valid_vibration(self):
        valid, error = validate_sensor_reading('vibration', 100.0, 'mg')
        assert valid is True

    def test_valid_tilt(self):
        valid, error = validate_sensor_reading('tilt', 45.0, '°')
        assert valid is True

    def test_invalid_sensor_type(self):
        valid, error = validate_sensor_reading('unknown_sensor', 1.0, 'x')
        assert valid is False
        assert 'unsupported' in error.lower()

    def test_wrong_unit_water_level(self):
        valid, error = validate_sensor_reading('water_level', 2.0, '°C')
        assert valid is False
        assert 'unit' in error.lower()

    def test_water_level_out_of_range_high(self):
        valid, error = validate_sensor_reading('water_level', 60.0, 'm')
        assert valid is False

    def test_water_level_out_of_range_low(self):
        valid, error = validate_sensor_reading('water_level', -1.0, 'm')
        assert valid is False

    def test_temperature_out_of_range(self):
        valid, error = validate_sensor_reading('temperature', 100.0, '°C')
        assert valid is False

    def test_humidity_out_of_range(self):
        valid, error = validate_sensor_reading('humidity', 150.0, '%')
        assert valid is False

    def test_sensor_types_constant(self):
        """Test SENSOR_TYPES constant has all expected types."""
        expected = {'water_level', 'temperature', 'humidity', 'rainfall', 'vibration', 'tilt'}
        assert set(SENSOR_TYPES.keys()) == expected
        for stype, info in SENSOR_TYPES.items():
            assert 'unit' in info
            assert 'range' in info
            assert 'description' in info


class TestWaterLevelIntegration:
    """Integration tests for water level sensor to River model."""

    def _setup_device_and_river(self, app, device_id='ESP32-WATER-001', river_name='Test River',
                                 current_level=2.0, danger_level=4.0, status='normal'):
        """Create district, device, and river. Returns (district_id, device_id, api_key, river_id)."""
        with app.app_context():
            district = District(name='Test District', province='Test Province')
            db.session.add(district)
            db.session.commit()
            district_id = district.id

            device = IoTDevice(
                device_id=device_id,
                name='Water Level Sensor',
                district_id=district_id,
                enabled=True,
            )
            api_key = 'water-test-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

            river = River(
                name=river_name,
                district_id=district_id,
                current_level=current_level,
                danger_level=danger_level,
                status=status,
            )
            db.session.add(river)
            db.session.commit()
            river_id = river.id

            return district_id, device.device_id, api_key, river_id

    def test_water_level_updates_river(self, app, client):
        """Test water level reading updates River model."""
        district_id, device_id, api_key, river_id = self._setup_device_and_river(app)

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 3.5, 'unit': 'm'}]
        })

        assert response.status_code == 201

        with app.app_context():
            river = db.session.get(River, river_id)
            assert river.current_level == 3.5
            assert river.status == 'rising'

    def test_water_level_triggers_rising(self, app, client):
        """Test water level at 80% triggers rising status."""
        district_id, device_id, api_key, river_id = self._setup_device_and_river(
            app, river_name='Rising River', current_level=2.0, danger_level=4.0, status='normal')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 3.2, 'unit': 'm'}]
        })

        assert response.status_code == 201
        with app.app_context():
            river = db.session.get(River, river_id)
            assert river.status == 'rising'

    def test_water_level_triggers_flooding(self, app, client):
        """Test water level at 100% triggers flooding status."""
        district_id, device_id, api_key, river_id = self._setup_device_and_river(
            app, river_name='Flood River', current_level=2.0, danger_level=4.0, status='normal')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 4.5, 'unit': 'm'}]
        })

        assert response.status_code == 201
        with app.app_context():
            river = db.session.get(River, river_id)
            assert river.status == 'flooding'

    def test_water_level_back_to_normal(self, app, client):
        """Test water level dropping back to normal."""
        district_id, device_id, api_key, river_id = self._setup_device_and_river(
            app, river_name='Normal River', current_level=3.5, danger_level=4.0, status='rising')

        headers = {'Authorization': f'Bearer {device_id}:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 2.0, 'unit': 'm'}]
        })

        assert response.status_code == 201
        with app.app_context():
            river = db.session.get(River, river_id)
            assert river.status == 'normal'

    def test_no_river_in_district(self, app, client):
        """Test reading ingested but no river update when no river in district."""
        with app.app_context():
            district = District(name='No River District', province='Test')
            db.session.add(district)
            db.session.commit()
            district_id = district.id

            device = IoTDevice(
                device_id='ESP32-NO-RIVER',
                name='No River Sensor',
                district_id=district_id,
                enabled=True,
            )
            api_key = 'no-river-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

        headers = {'Authorization': f'Bearer ESP32-NO-RIVER:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 2.0, 'unit': 'm'}]
        })

        assert response.status_code == 201
        with app.app_context():
            readings = SensorReading.query.all()
            assert len(readings) == 1

    def test_river_without_danger_level(self, app, client):
        """Test reading ingested but no status change when river has no danger level."""
        with app.app_context():
            district = District(name='No Danger District', province='Test')
            db.session.add(district)
            db.session.commit()
            district_id = district.id

            river = River(name='No Danger River', district_id=district_id, current_level=2.0)
            db.session.add(river)
            db.session.commit()
            river_id = river.id

            device = IoTDevice(
                device_id='ESP32-NO-DANGER',
                name='No Danger Sensor',
                district_id=district_id,
                enabled=True,
            )
            api_key = 'no-danger-key'
            device.api_key_hash = IoTDevice.hash_api_key(api_key)
            db.session.add(device)
            db.session.commit()

        headers = {'Authorization': f'Bearer ESP32-NO-DANGER:{api_key}'}
        response = client.post('/api/iot/telemetry', headers=headers, json={
            'readings': [{'sensor_type': 'water_level', 'value': 10.0, 'unit': 'm'}]
        })

        assert response.status_code == 201
        with app.app_context():
            river = db.session.get(River, river_id)
            assert river.current_level == 10.0