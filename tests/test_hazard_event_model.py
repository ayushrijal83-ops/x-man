"""Tests for Hazard Event model."""
import pytest
from app.extensions import db
from app.models import Incident, District, River, RoadSegment
from datetime import datetime


def _make_district(app):
    with app.app_context():
        district = District(name='Test District', province='Test Province')
        db.session.add(district)
        db.session.commit()
        return district.id


def _make_river(app, district_id):
    with app.app_context():
        river = River(name='Test River', district_id=district_id, current_level=2.0, danger_level=4.0, status='normal')
        db.session.add(river)
        db.session.commit()
        return river.id


def _make_road_segment(app, district_id):
    with app.app_context():
        road = RoadSegment(name='Test Road', district_id=district_id, status='open')
        db.session.add(road)
        db.session.commit()
        return road.id


class TestIncidentModel:
    """Tests for extended Incident/HazardEvent model."""

    def test_incident_creation_with_new_fields(self, app):
        """Test creating incident with new hazard event fields."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='high',
                source='iot',
                district_id=district_id,
                location='Test Location',
                latitude=27.5,
                longitude=85.5,
                title='Test Flood',
                description='Test flood event',
                source_reference='device_123',
                status='detected',
                confidence=0.8,
                detected_at=datetime.utcnow(),
            )
            db.session.add(incident)
            db.session.commit()

            assert incident.id is not None
            assert incident.event_type == 'flood'
            assert incident.severity == 'high'
            assert incident.source == 'iot'
            assert incident.district_id == district_id
            assert incident.latitude == 27.5
            assert incident.longitude == 85.5
            assert incident.title == 'Test Flood'
            assert incident.source_reference == 'device_123'
            assert incident.status == 'detected'
            assert incident.confidence == 0.8

    def test_incident_with_river_association(self, app):
        """Test incident with river_id FK."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                river_id=river_id,
                title='River Flood',
                description='Flood on test river',
                source_reference='river_1',
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()

            assert incident.river_id == river_id
            assert incident.river is not None
            assert incident.river.id == river_id

    def test_incident_with_road_segment_association(self, app):
        """Test incident with road_segment_id FK."""
        district_id = _make_district(app)
        road_id = _make_road_segment(app, district_id)

        with app.app_context():
            incident = Incident(
                event_type='road_damage',
                severity='high',
                source='authority',
                district_id=district_id,
                road_segment_id=road_id,
                title='Road Damage',
                description='Road damage event',
                source_reference='auth_1',
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()

            assert incident.road_segment_id == road_id
            assert incident.road_segment is not None
            assert incident.road_segment.id == road_id

    def test_incident_to_dict(self, app):
        """Test incident to_dict method."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='landslide',
                severity='critical',
                source='citizen_report',
                district_id=district_id,
                location='Test Location',
                title='Test Landslide',
                description='Large landslide',
                source_reference='user_1',
                status='confirmed',
                confidence=0.9,
            )
            db.session.add(incident)
            db.session.commit()

            d = incident.to_dict()
            assert d['event_type'] == 'landslide'
            assert d['severity'] == 'critical'
            assert d['source'] == 'citizen_report'
            assert d['district_id'] == district_id
            assert d['title'] == 'Test Landslide'
            assert d['status'] == 'confirmed'
            assert d['confidence'] == 0.9

    def test_can_transition_to(self, app):
        """Test status transition validation."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()

            assert incident.can_transition_to('investigating') is True
            assert incident.can_transition_to('confirmed') is False
            assert incident.can_transition_to('rejected') is True
            assert incident.can_transition_to('resolved') is False

            incident.status = 'investigating'
            assert incident.can_transition_to('confirmed') is True
            assert incident.can_transition_to('rejected') is True
            assert incident.can_transition_to('detected') is False

            incident.status = 'confirmed'
            assert incident.can_transition_to('resolved') is True
            assert incident.can_transition_to('investigating') is False

    def test_transition_status(self, app):
        """Test status transition."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()

            old_status = incident.transition_status('investigating')
            assert old_status == 'detected'
            assert incident.status == 'investigating'

            old_status = incident.transition_status('confirmed')
            assert old_status == 'investigating'
            assert incident.status == 'confirmed'

            old_status = incident.transition_status('resolved')
            assert old_status == 'confirmed'
            assert incident.status == 'resolved'
            assert incident.resolved_at is not None

    def test_invalid_transition_raises_error(self, app):
        """Test invalid status transition raises ValueError."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()

            with pytest.raises(ValueError):
                incident.transition_status('resolved')  # Can't go from detected to resolved

            with pytest.raises(ValueError):
                incident.transition_status('invalid_status')  # Invalid status


class TestIncidentConstants:
    """Tests for hazard event constants."""

    def test_hazard_types(self):
        from app.models.incident import HAZARD_TYPES
        assert HAZARD_TYPES == ['flood', 'landslide', 'road_damage']

    def test_hazard_sources(self):
        from app.models.incident import HAZARD_SOURCES
        assert HAZARD_SOURCES == ['iot', 'citizen_report', 'authority', 'system']

    def test_hazard_severity(self):
        from app.models.incident import HAZARD_SEVERITY
        assert HAZARD_SEVERITY == ['low', 'medium', 'high', 'critical']

    def test_hazard_status(self):
        from app.models.incident import HAZARD_STATUS
        assert HAZARD_STATUS == ['detected', 'investigating', 'confirmed', 'resolved', 'rejected']

    def test_valid_status_transitions(self):
        from app.models.incident import VALID_STATUS_TRANSITIONS
        assert VALID_STATUS_TRANSITIONS == {
            'detected': ['investigating', 'rejected'],
            'investigating': ['confirmed', 'rejected'],
            'confirmed': ['resolved'],
            'resolved': [],
            'rejected': [],
        }