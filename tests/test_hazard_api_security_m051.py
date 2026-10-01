"""M05.1: citizens can't control severity/status/source/incident via POST /api/hazards."""
import io

import pytest
from PIL import Image

from app.extensions import db
from app.models import Authority, District, Incident, Notification, User
from app.services.hazard_event_service import create_hazard_event, report_hazard


@pytest.fixture
def world(app, tmp_path):
    app.config['REPORT_UPLOAD_DIR'] = str(tmp_path / 'reports')
    with app.app_context():
        a = District(name='District A', province='P')
        db.session.add(a)
        db.session.commit()
        auth = Authority(name='Auth A', category='roads', district_id=a.id)
        db.session.add(auth)
        db.session.commit()
        ids = {'a': a.id}
        for username, role, authority_id in [('citizen', 'citizen', None), ('citizen2', 'citizen', None),
                                             ('auth', 'authority', auth.id), ('admin', 'admin', None)]:
            user = User(username=username, email=f'{username}@t.np', role=role,
                        district_id=a.id if role != 'admin' else None, authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            db.session.commit()
            ids[username] = user.id
        return ids


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _citizen_post(client, **extra):
    _login(client, 'citizen')
    return client.post('/api/hazards', json={'event_type': 'road_damage', 'latitude': 27.7,
                                             'longitude': 85.3, **extra})


def _escalations():
    return Notification.query.filter_by(type='hazard_escalated').count()


@pytest.mark.parametrize('severity', ['critical', 'high', 'low', 'bogus'])
def test_citizen_severity_ignored_on_create(app, client, world, severity):
    response = _citizen_post(client, severity=severity)
    assert response.status_code == 201
    event = response.get_json()['event']
    assert event['severity'] == 'medium'
    with app.app_context():
        assert db.session.get(Incident, event['id']).severity == 'medium'


@pytest.mark.parametrize('severity', ['critical', 'high'])
def test_citizen_severity_cannot_escalate_existing_event(app, client, world, severity):
    with app.app_context():
        event_id = create_hazard_event('road_damage', 'low', 'iot', district_id=world['a'],
                                       latitude=27.7, longitude=85.3).id
    response = _citizen_post(client, severity=severity)
    assert response.status_code == 200
    assert response.get_json()['event']['id'] == event_id
    with app.app_context():
        incident = db.session.get(Incident, event_id)
        assert incident.severity == 'low'
        assert incident.report_count == 2
        assert _escalations() == 0


@pytest.mark.parametrize('status', ['confirmed', 'investigating', 'resolved', 'rejected'])
def test_citizen_status_ignored(app, client, world, status):
    event = _citizen_post(client, status=status).get_json()['event']
    assert event['status'] == 'detected'
    with app.app_context():
        assert Notification.query.filter_by(type='hazard_confirmed').count() == 0
        assert Notification.query.filter_by(type='hazard_resolved').count() == 0


@pytest.mark.parametrize('source', ['iot', 'authority', 'system'])
def test_citizen_source_ignored(app, client, world, source):
    event = _citizen_post(client, source=source).get_json()['event']
    assert event['source'] == 'citizen_report'


def test_citizen_cannot_spoof_role(app, client, world):
    response = _citizen_post(client, role='admin', user_id=world['admin'], reporter_id=world['admin'],
                             source='authority', severity='critical')
    event = response.get_json()['event']
    assert (event['source'], event['severity']) == ('citizen_report', 'medium')
    assert 'source_reference' not in event  # still serialized as a non-manager
    with app.app_context():
        assert db.session.get(Incident, event['id']).source_reference == f"user_{world['citizen']}"


def test_citizen_incident_id_cannot_mutate_other_event(app, client, world):
    with app.app_context():
        # different type and far away: not a dedup match
        target = create_hazard_event('flood', 'low', 'iot', district_id=world['a'],
                                     latitude=28.5, longitude=84.0).id
    response = _citizen_post(client, incident_id=target, id=target, severity='critical', status='confirmed')
    assert response.status_code == 201
    assert response.get_json()['event']['id'] != target
    with app.app_context():
        incident = db.session.get(Incident, target)
        assert (incident.severity, incident.status, incident.report_count) == ('low', 'detected', 1)


def test_service_guard_covers_any_citizen_caller(app, world):
    with app.app_context():
        incident, created = report_hazard('landslide', 'critical', 'citizen_report', district_id=world['a'])
        assert created and incident.severity == 'medium'
        incident, created = report_hazard('landslide', 'critical', 'citizen_report', escalate=True,
                                          district_id=world['a'])
        assert not created and incident.severity == 'medium'
        assert _escalations() == 0


def test_normal_citizen_submission_still_works(app, client, world):
    response = _citizen_post(client, description='Big crack', location='Near bridge')
    assert response.status_code == 201
    body = response.get_json()
    assert body['created'] is True
    assert body['event']['district_id'] == world['a']
    with app.app_context():
        assert Notification.query.filter_by(user_id=world['citizen2'], type='hazard_detected').count() == 1


@pytest.mark.parametrize('who', ['auth', 'admin'])
def test_managers_keep_severity_control(app, client, world, who):
    _login(client, who)
    response = client.post('/api/hazards', json={'event_type': 'landslide', 'severity': 'critical',
                                                 'district_id': world['a']})
    assert response.status_code == 201
    assert response.get_json()['event']['severity'] == 'critical'
    assert response.get_json()['event']['source'] == 'authority'
    # authority evidence may still escalate an existing event
    with app.app_context():
        event_id = create_hazard_event('flood', 'low', 'iot', district_id=world['a']).id
    response = client.post('/api/hazards', json={'event_type': 'flood', 'severity': 'high',
                                                 'district_id': world['a']})
    assert response.get_json()['event']['id'] == event_id
    assert response.get_json()['event']['severity'] == 'high'
    with app.app_context():
        assert _escalations() > 0


def test_manager_invalid_severity_still_rejected(client, world):
    _login(client, 'admin')
    response = client.post('/api/hazards', json={'event_type': 'flood', 'severity': 'bogus'})
    assert response.status_code == 400


def test_m05_photo_report_unchanged(app, client, world):
    _login(client, 'citizen')
    buf = io.BytesIO()
    Image.new('RGB', (64, 48)).save(buf, format='JPEG')
    response = client.post('/api/reports', content_type='multipart/form-data', data={
        'hazard_type': 'road_damage', 'district_id': str(world['a']), 'severity': 'critical',
        'image': (io.BytesIO(buf.getvalue()), 'p.jpg', 'image/jpeg')})
    assert response.status_code == 201
    with app.app_context():
        incident = Incident.query.one()
        assert (incident.severity, incident.source, incident.status) == ('medium', 'citizen_report', 'detected')
