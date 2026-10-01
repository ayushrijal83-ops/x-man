"""Tests for Hazard Event Service."""
import pytest
from app.extensions import db
from app.models import IncidentStatusHistory
from app.models import Incident, District, River, RoadSegment
from app.services.hazard_event_service import (
    create_hazard_event,
    find_active_related_event,
    transition_event_status,
    resolve_event,
    reject_event,
    escalate_to_investigating,
    confirm_event,
    update_event_from_iot,
    auto_create_flood_event_from_river,
    get_active_events_for_district,
    get_events_by_type,
    get_events_by_source,
    get_events_near_location,
    get_event_statistics,
    HAZARD_TYPES, HAZARD_SOURCES, HAZARD_SEVERITY, HAZARD_STATUS,
    VALID_STATUS_TRANSITIONS,
)
from datetime import datetime, timedelta
from unittest.mock import Mock


def _make_district(app):
    with app.app_context():
        district = District(name='Test District', province='Test Province')
        db.session.add(district)
        db.session.commit()
        return district.id


def _make_river(app, district_id, name='Test River', current_level=2.0, danger_level=4.0):
    with app.app_context():
        river = River(name=name, district_id=district_id, current_level=current_level, danger_level=danger_level, status='normal')
        db.session.add(river)
        db.session.commit()
        return river.id


def _make_device(app, district_id):
    from app.models import IoTDevice
    with app.app_context():
        device = IoTDevice(
            device_id='TEST-DEVICE',
            name='Test Device',
            district_id=district_id,
            latitude=27.5,
            longitude=85.5,
            enabled=True,
        )
        device.api_key_hash = IoTDevice.hash_api_key('test-key')
        db.session.add(device)
        db.session.commit()
        return device


class TestHazardEventService:
    """Tests for hazard event service functions."""

    def test_create_hazard_event_valid(self, app):
        """Test creating a valid hazard event."""
        district_id = _make_district(app)

        with app.app_context():
            incident = create_hazard_event(
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
                confidence=0.8,
            )
            
            assert incident.id is not None
            assert incident.event_type == 'flood'
            assert incident.severity == 'high'
            assert incident.source == 'iot'
            assert incident.district_id == district_id

    def test_create_hazard_event_invalid_type(self, app):
        """Test creating event with invalid type raises error."""
        district_id = _make_district(app)

        with app.app_context():
            with pytest.raises(ValueError):
                create_hazard_event(
                    event_type='invalid_type',
                    severity='medium',
                    source='iot',
                    district_id=district_id,
                )

    def test_create_hazard_event_invalid_severity(self, app):
        """Test creating event with invalid severity raises error."""
        district_id = _make_district(app)

        with app.app_context():
            with pytest.raises(ValueError):
                create_hazard_event(
                    event_type='flood',
                    severity='invalid_severity',
                    source='iot',
                    district_id=district_id,
                )

    def test_create_hazard_event_invalid_source(self, app):
        """Test creating event with invalid source raises error."""
        district_id = _make_district(app)

        with app.app_context():
            with pytest.raises(ValueError):
                create_hazard_event(
                    event_type='flood',
                    severity='medium',
                    source='invalid_source',
                    district_id=district_id,
                )

    def test_create_hazard_event_invalid_coordinates(self, app):
        """Test creating event with invalid coordinates raises error."""
        district_id = _make_district(app)

        with app.app_context():
            with pytest.raises(ValueError):
                create_hazard_event(
                    event_type='flood',
                    severity='medium',
                    source='iot',
                    district_id=district_id,
                    latitude=100,  # Invalid
                )

    def test_create_hazard_event_invalid_district(self, app):
        """Test creating event with invalid district raises error."""
        with app.app_context():
            with pytest.raises(ValueError):
                create_hazard_event(
                    event_type='flood',
                    severity='medium',
                    source='iot',
                    district_id=99999,
                )

    def test_create_hazard_event_with_river(self, app):
        """Test creating event with river association."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id)

        with app.app_context():
            incident = create_hazard_event(
                event_type='flood',
                severity='high',
                source='iot',
                district_id=district_id,
                river_id=river_id,
            )
            
            assert incident.river_id == river_id

    def test_find_active_related_event_same_river(self, app):
        """Test finding related event by river."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id)

        with app.app_context():
            # Create first event
            incident1 = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                river_id=river_id,
                status='detected',
            )
            db.session.add(incident1)
            db.session.commit()
            
            # Find related - should find incident1
            related = find_active_related_event(
                event_type='flood',
                river_id=river_id,
            )
            assert related is not None
            assert related.id == incident1.id

    def test_find_active_related_event_different_river(self, app):
        """Test not finding event for different river."""
        district_id = _make_district(app)
        river_id1 = _make_river(app, district_id, 'River 1')
        river_id2 = _make_river(app, district_id, 'River 2')

        with app.app_context():
            incident1 = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                river_id=river_id1,
                status='detected',
            )
            db.session.add(incident1)
            db.session.commit()
            
            # Search for river2 - should not find
            related = find_active_related_event(
                event_type='flood',
                river_id=river_id2,
            )
            
            assert related is None

    def test_find_active_related_event_district(self, app):
        """Test finding related event by district."""
        district_id = _make_district(app)

        with app.app_context():
            incident1 = Incident(
                event_type='landslide',
                severity='high',
                source='citizen_report',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident1)
            db.session.commit()
            
            related = find_active_related_event(
                event_type='landslide',
                district_id=district_id,
            )
            assert related is not None
            assert related.id == incident1.id

    def test_find_active_related_event_geo(self, app):
        """Test finding related event by geographic proximity."""
        district_id = _make_district(app)

        with app.app_context():
            incident1 = Incident(
                event_type='flood',
                severity='medium',
                source='citizen_report',
                district_id=district_id,
                latitude=27.5,
                longitude=85.5,
                status='detected',
            )
            db.session.add(incident1)
            db.session.commit()
            
            # Search near the same location
            related = find_active_related_event(
                event_type='flood',
                latitude=27.501,  # Very close
                longitude=85.501,
            )
            assert related is not None
            assert related.id == incident1.id

    def test_find_active_related_event_expired(self, app):
        """Test finding related event respects time window."""
        district_id = _make_district(app)

        with app.app_context():
            # Use a fixed time reference
            fixed_time = datetime.utcnow()
            
            # Create old event (outside default 24h window)
            old_incident = Incident(
                event_type='flood',
                severity='medium',
                source='iot',
                district_id=district_id,
                status='detected',
                detected_at=fixed_time - timedelta(hours=48),
                updated_at=fixed_time - timedelta(hours=48),  # no evidence for 48h
            )
            db.session.add(old_incident)
            db.session.commit()
            
            # Search with default 24h window - should not find
            related = find_active_related_event(
                event_type='flood',
                district_id=district_id,
                hours=24
            )
            
            assert related is None
            
            # Search with 72h window - should find (use generous window to avoid timing issues)
            related = find_active_related_event(
                event_type='flood',
                district_id=district_id,
                hours=72
            )
            assert related is not None

    def test_transition_event_status_valid(self, app):
        """Test valid status transition."""
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
            
            old_status = transition_event_status(incident, 'investigating')
            
            assert old_status == 'detected'
            assert incident.status == 'investigating'

    def test_transition_event_status_invalid(self, app):
        """Test invalid status transition raises error."""
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
                transition_event_status(incident, 'resolved')  # Invalid from detected

    def test_resolve_event(self, app):
        """Test resolving an event."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='high',
                source='authority',
                district_id=district_id,
                status='confirmed',
            )
            db.session.add(incident)
            db.session.commit()
            
            resolve_event(incident, 'Water level returned to normal')
            
            assert incident.status == 'resolved'
            assert incident.resolved_at is not None
            # M09: the note is internal (status history), no longer appended to the public description
            assert incident.description is None
            assert IncidentStatusHistory.query.filter_by(incident_id=incident.id).one().note == \
                'Water level returned to normal'

    def test_reject_event(self, app):
        """Test rejecting an event."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='citizen_report',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            
            reject_event(incident, 'False alarm')
            
            assert incident.status == 'rejected'
            # M09: the reason is internal (status history), no longer appended to the public description
            assert incident.description is None
            assert IncidentStatusHistory.query.filter_by(incident_id=incident.id).one().note == 'False alarm'

    def test_confirm_event(self, app):
        """Test confirming an event."""
        district_id = _make_district(app)

        with app.app_context():
            incident = Incident(
                event_type='landslide',
                severity='high',
                source='citizen_report',
                district_id=district_id,
                status='investigating',
            )
            db.session.add(incident)
            db.session.commit()
            
            confirm_event(incident)
            
            assert incident.status == 'confirmed'

    def test_update_event_from_iot(self, app):
        """Test updating event from IoT data."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='low',
                source='iot',
                district_id=district_id,
                river_id=river_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            
            risk_assessment = {
                'risk_level': 3,  # flooding
                'status': 'flooding',
            }
            
            updated = update_event_from_iot(incident, risk_assessment, 'device_1')

            assert updated is True
            assert incident.severity == 'high'  # flooding -> high
            assert incident.report_count == 2
            assert incident.source_reference == 'device_1'
            # sensor evidence never moves the lifecycle; that is an authority decision
            assert incident.status == 'detected'

    def test_auto_create_flood_event_from_river(self, app):
        """Test auto-creating flood event from river risk."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id, current_level=3.5, danger_level=4.0)  # rising

        with app.app_context():
            river = db.session.get(River, river_id)
            risk = {'risk_level': 2, 'status': 'rising', 'percentage': 87.5, 'reason': 'Water level at 87.5% of danger mark'}
            
            incident = auto_create_flood_event_from_river(river, risk)
            
            assert incident is not None
            assert incident.event_type == 'flood'
            assert incident.river_id == river_id
            assert incident.source == 'iot'
            assert incident.status == 'detected'

    def test_auto_create_flood_event_deduplication(self, app):
        """Test deduplication when creating flood events."""
        district_id = _make_district(app)
        river_id = _make_river(app, district_id, current_level=3.5, danger_level=4.0)

        with app.app_context():
            river = db.session.get(River, river_id)
            risk = {'risk_level': 2, 'status': 'rising', 'percentage': 87.5, 'reason': 'Water level at 87.5% of danger mark'}
            
            # Create first event
            incident1 = auto_create_flood_event_from_river(river, risk)
            assert incident1 is not None
            id1 = incident1.id
            
            # Create second event for same river - should return same event
            incident2 = auto_create_flood_event_from_river(river, risk)
            assert incident2 is not None
            assert incident2.id == id1  # Same event, updated

    def test_get_active_events_for_district(self, app):
        """Test getting active events for district."""
        district_id = _make_district(app)

        with app.app_context():
            # Create events with different statuses
            incident1 = Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected')
            incident2 = Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='investigating')
            incident3 = Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='resolved')
            db.session.add_all([incident1, incident2, incident3])
            db.session.commit()
            
            events = get_active_events_for_district(district_id)
            
            assert len(events) == 2  # Only detected and investigating
            statuses = [e.status for e in events]
            assert 'detected' in statuses
            assert 'investigating' in statuses
            assert 'resolved' not in statuses

    def test_get_events_by_type(self, app):
        """Test getting events by type."""
        district_id = _make_district(app)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='flood', severity='high', source='citizen_report', district_id=district_id, status='investigating'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='detected'),
            ])
            db.session.commit()

            assert len(get_events_by_type('flood')) == 2
            assert len(get_events_by_type('landslide')) == 1

    def test_get_event_statistics(self, app):
        """Test getting event statistics."""
        district_id = _make_district(app)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='flood', severity='high', source='citizen_report', district_id=district_id, status='confirmed'),
                Incident(event_type='landslide', severity='critical', source='authority', district_id=district_id, status='investigating'),
                Incident(event_type='road_damage', severity='low', source='system', district_id=district_id, status='resolved'),
            ])
            db.session.commit()

            stats = get_event_statistics()

            assert stats['total'] >= 4
            assert stats['by_status']['detected'] >= 1
            assert stats['by_type']['flood'] >= 2
            assert stats['by_source']['iot'] >= 1
            assert stats['by_severity']['high'] >= 1
