"""Tests for Hazard Events API."""
import pytest
from app.extensions import db
from app.models import Incident, District, River, RoadSegment, User, Authority
from app.services.hazard_event_service import HAZARD_TYPES, HAZARD_SEVERITY, HAZARD_SOURCES
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


def _make_user(app, district_id, authority_id=None, role='citizen', username='testuser'):
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


def _make_authority(app, district_id):
    with app.app_context():
        authority = Authority(
            name='Test Authority',
            category='water',
            district_id=district_id,
        )
        db.session.add(authority)
        db.session.flush()
        db.session.commit()
        return authority.id


def _login_user(client, username='testuser'):
    return client.post('/auth/login', data={'username': username, 'password': 'password'})


def _login_authority(client, username='authority_user'):
    return client.post('/auth/authority/login', data={'username': username, 'password': 'password'})


class TestHazardEventsAPI:
    """Tests for Hazard Events API endpoints."""

    def test_list_hazards_authenticated(self, app, client):
        """Test listing hazards requires authentication."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        response = client.get('/api/hazards')
        assert response.status_code == 200
        data = response.get_json()
        assert 'events' in data

    def test_list_hazards_unauthenticated(self, app, client):
        """Test listing hazards fails without auth."""
        response = client.get('/api/hazards')
        assert response.status_code == 401

    def test_list_hazards_with_filters(self, app, client):
        """Test listing hazards with filters."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='detected'),
                Incident(event_type='flood', severity='high', source='authority', district_id=district_id, status='confirmed'),
            ])
            db.session.commit()

        # Filter by event_type
        response = client.get('/api/hazards?event_type=flood')
        assert response.status_code == 200
        data = response.get_json()
        assert all(e['event_type'] == 'flood' for e in data['events'])

        # Filter by severity
        response = client.get('/api/hazards?severity=high')
        assert response.status_code == 200
        data = response.get_json()
        assert all(e['severity'] == 'high' for e in data['events'])

        # Filter by status
        response = client.get('/api/hazards?status=detected')
        assert response.status_code == 200
        data = response.get_json()
        assert all(e['status'] == 'detected' for e in data['events'])

    def test_get_hazard_by_id(self, app, client):
        """Test getting a specific hazard event."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='high',
                source='iot',
                district_id=district_id,
                title='Test Flood',
                description='Test flood',
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            event_id = incident.id

        response = client.get(f'/api/hazards/{event_id}')
        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == event_id
        assert data['title'] == 'Test Flood'

    def test_create_hazard_as_authority(self, app, client):
        """Test authority can create hazard event."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        response = client.post('/api/hazards', json={
            'event_type': 'flood',
            'severity': 'high',
            'source': 'authority',
            'district_id': district_id,
            'title': 'Authority Flood Alert',
            'description': 'Flood detected by authority',
            'source_reference': 'auth_1',
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['event']['event_type'] == 'flood'
        assert data['event']['severity'] == 'high'
        assert data['event']['source'] == 'authority'

    def test_citizen_report_is_forced_to_citizen_source(self, app, client):
        """Citizens can report, but cannot choose source or status."""
        district_id = _make_district(app)
        _make_user(app, district_id, role='citizen', username='citizen_user')

        _login_user(client, username='citizen_user')

        response = client.post('/api/hazards', json={
            'event_type': 'flood',
            'severity': 'high',
            'source': 'authority',
            'status': 'confirmed',
            'district_id': district_id,
        })

        assert response.status_code == 201
        event = response.get_json()['event']
        assert event['source'] == 'citizen_report'
        assert event['status'] == 'detected'
        assert 'source_reference' not in event

    def test_create_hazard_missing_fields(self, app, client):
        """Test creating hazard event with missing required fields."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        response = client.post('/api/hazards', json={
            'severity': 'high',
            # Missing event_type
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'event_type' in data['error']

    def test_create_hazard_invalid_type(self, app, client):
        """Test creating hazard event with invalid type."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        response = client.post('/api/hazards', json={
            'event_type': 'invalid_type',
            'severity': 'high',
            'source': 'authority',
            'district_id': district_id,
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid hazard type' in data['error']

    def test_create_hazard_invalid_severity(self, app, client):
        """Test creating hazard event with invalid severity."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        response = client.post('/api/hazards', json={
            'event_type': 'flood',
            'severity': 'invalid_severity',
            'source': 'authority',
            'district_id': district_id,
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid severity' in data['error']

    def test_create_hazard_invalid_coordinates(self, app, client):
        """Test creating hazard event with invalid coordinates."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        response = client.post('/api/hazards', json={
            'event_type': 'flood',
            'severity': 'high',
            'source': 'authority',
            'district_id': district_id,
            'latitude': 100,
            'longitude': 85.5,
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Latitude must be between' in data['error']

    def test_update_hazard_as_authority(self, app, client):
        """Test authority can update hazard event."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='authority',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            event_id = incident.id

        response = client.patch(f'/api/hazards/{event_id}', json={
            'severity': 'high',
            'status': 'investigating',
            'description': 'Updated description',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['event']['severity'] == 'high'
        assert data['event']['status'] == 'investigating'
        assert data['event']['description'] == 'Updated description'

    def test_update_hazard_invalid_status_transition(self, app, client):
        """Test invalid status transition rejected."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='authority',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            event_id = incident.id

        response = client.patch(f'/api/hazards/{event_id}', json={
            'status': 'resolved',  # Invalid from detected
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid transition' in data['error']

    def test_change_hazard_status_endpoint(self, app, client):
        """Test dedicated status change endpoint."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

        with app.app_context():
            incident = Incident(
                event_type='flood',
                severity='medium',
                source='authority',
                district_id=district_id,
                status='detected',
            )
            db.session.add(incident)
            db.session.commit()
            event_id = incident.id

        response = client.post(f'/api/hazards/{event_id}/status', json={
            'status': 'investigating',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['event']['status'] == 'investigating'
        assert data['previous_status'] == 'detected'
        assert data['new_status'] == 'investigating'

    def test_resolve_hazard(self, app, client):
        """Test resolving a hazard event."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

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
            event_id = incident.id

        response = client.post(f'/api/hazards/{event_id}/resolve', json={
            'resolution_notes': 'Water level returned to normal',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['event']['status'] == 'resolved'
        assert 'Resolution: Water level returned to normal' in data['event']['description']

    def test_reject_hazard(self, app, client):
        """Test rejecting a hazard event."""
        district_id = _make_district(app)
        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')

        _login_authority(client)

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
            event_id = incident.id

        response = client.post(f'/api/hazards/{event_id}/reject', json={
            'reason': 'False alarm',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['event']['status'] == 'rejected'
        assert 'Rejection reason: False alarm' in data['event']['description']

    def test_get_district_active_events(self, app, client):
        """Test getting active events for district."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='investigating'),
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='resolved'),
            ])
            db.session.commit()

        response = client.get(f'/api/hazards/district/{district_id}/active')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['events']) == 2
        statuses = [e['status'] for e in data['events']]
        assert 'detected' in statuses
        assert 'investigating' in statuses
        assert 'resolved' not in statuses

    def test_get_events_by_type(self, app, client):
        """Test getting events by type."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='flood', severity='high', source='citizen_report', district_id=district_id, status='investigating'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='detected'),
            ])
            db.session.commit()

        response = client.get('/api/hazards/types/flood')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['events']) == 2
        assert all(e['event_type'] == 'flood' for e in data['events'])

    def test_get_events_by_type_invalid(self, app, client):
        """Test getting events by invalid type."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        response = client.get('/api/hazards/types/invalid_type')
        assert response.status_code == 400

    def test_get_events_by_source(self, app, client):
        """Test getting events by source."""
        district_id = _make_district(app)
        _make_user(app, district_id)

        _login_user(client)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='detected'),
            ])
            db.session.commit()

        response = client.get('/api/hazards/sources/iot')
        assert response.status_code == 200
        data = response.get_json()
        assert all(e['source'] == 'iot' for e in data['events'])

    def test_statistics_endpoint(self, app, client):
        """Test statistics endpoint (authority only)."""
        district_id = _make_district(app)
        _make_user(app, district_id, role='citizen', username='citizen_user')

        _login_user(client, username='citizen_user')

        response = client.get('/api/hazards/statistics')
        assert response.status_code == 403

        authority_id = _make_authority(app, district_id)
        _make_user(app, district_id, authority_id, role='authority', username='authority_user')
        client.get('/auth/logout')
        _login_authority(client)

        with app.app_context():
            db.session.add_all([
                Incident(event_type='flood', severity='medium', source='iot', district_id=district_id, status='detected'),
                Incident(event_type='landslide', severity='high', source='citizen_report', district_id=district_id, status='investigating'),
            ])
            db.session.commit()

        response = client.get('/api/hazards/statistics')
        assert response.status_code == 200
        data = response.get_json()
        assert 'total' in data
        assert 'by_status' in data
        assert 'by_type' in data
        assert 'by_source' in data
        assert 'by_severity' in data