"""M03 notification system: model, service, targeting, dedup, API/RBAC, IoT flood flow, earthquake, UI."""
import pytest

from app.extensions import db
from app.models import Authority, District, Incident, IoTDevice, Notification, River, User
from app.services import notification_service
from app.services.hazard_event_service import (
    add_evidence, create_hazard_event, reject_event, resolve_event, transition_event_status,
    update_event,
)


@pytest.fixture
def world(app):
    """District A (river, gauge, authority) and district B, with one user per role/place."""
    with app.app_context():
        a = District(name='District A', province='P1')
        b = District(name='District B', province='P1')
        db.session.add_all([a, b])
        db.session.commit()
        river = River(name='Koshi', district_id=a.id, current_level=1.0, danger_level=4.0, status='normal')
        auth_a = Authority(name='Auth A', category='water', district_id=a.id)
        auth_b = Authority(name='Auth B', category='water', district_id=b.id)
        db.session.add_all([river, auth_a, auth_b])
        db.session.commit()
        device = IoTDevice(device_id='ESP32-M03', name='Gauge', district_id=a.id, river_id=river.id, enabled=True)
        device.api_key_hash = IoTDevice.hash_api_key('k')
        db.session.add(device)
        users = {}
        for username, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None),
            ('citizen_b', 'citizen', b.id, None),
            ('auth_a', 'authority', None, auth_a.id),  # responsible via Authority, no home district
            ('auth_b', 'authority', b.id, auth_b.id),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=username, email=f'{username}@t.np', role=role,
                        district_id=district_id, authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[username] = user
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'river': river.id, 'users': {k: u.id for k, u in users.items()}}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _notes(user_id, type=None):
    query = Notification.query.filter_by(user_id=user_id)
    if type:
        query = query.filter_by(type=type)
    return query.all()


def _telemetry(client, level):
    response = client.post('/api/iot/telemetry', headers={'Authorization': 'Bearer ESP32-M03:k'},
                           json={'readings': [{'sensor_type': 'water_level', 'value': level, 'unit': 'm'}]})
    assert response.status_code == 201


class TestModelAndService:
    def test_notification_links_to_hazard_and_defaults_unread(self, app, world):
        with app.app_context():
            incident = create_hazard_event('landslide', 'high', 'authority', district_id=world['a'])
            note = _notes(world['users']['citizen_a'])[0]
            assert note.is_read is False
            assert note.incident.id == incident.id
            assert note.severity == 'high'
            assert note.to_dict()['hazard'] == {'id': incident.id, 'event_type': 'landslide', 'status': 'detected',
                                                'district_name': 'District A', 'affected_districts': ['District A']}

    def test_create_notification_validates(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            with pytest.raises(ValueError):
                notification_service.create_notification(uid, 'made_up', 'x')
            with pytest.raises(ValueError):
                notification_service.create_notification(uid, 'system', '')
            with pytest.raises(ValueError):
                notification_service.create_notification(uid, 'system', 'x', severity='extreme')
            notification_service.create_notification(uid, 'river_alert', 'legacy type still accepted')

    def test_title_is_required_at_db_level(self, app, world):
        with app.app_context():
            db.session.add(Notification(user_id=world['users']['citizen_a'], type='system'))
            with pytest.raises(Exception):
                db.session.commit()
            db.session.rollback()

    def test_targeting_district_responsible_authority_and_admin(self, app, world):
        u = world['users']
        with app.app_context():
            create_hazard_event('landslide', 'high', 'authority', district_id=world['a'])
            got = {uid for uid in u.values() if _notes(uid, 'hazard_detected')}
            assert got == {u['citizen_a'], u['auth_a'], u['admin']}
            assert all(len(_notes(uid)) == 1 for uid in got)

    def test_hazard_without_district_goes_to_admins_only(self, app, world):
        u = world['users']
        with app.app_context():
            create_hazard_event('road_damage', 'low', 'system')
            assert {uid for uid in u.values() if _notes(uid)} == {u['admin']}

    def test_lifecycle_notifications(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('flood', 'medium', 'authority', district_id=world['a'])
            transition_event_status(incident, 'investigating')  # no notification
            transition_event_status(incident, 'confirmed')
            resolve_event(incident, 'water receded')
            assert [n.type for n in sorted(_notes(uid), key=lambda n: n.id)] == \
                ['hazard_detected', 'hazard_confirmed', 'hazard_resolved']

    def test_reject_sends_nothing_extra(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('flood', 'medium', 'authority', district_id=world['a'])
            reject_event(incident, 'false alarm')
            assert [n.type for n in _notes(uid)] == ['hazard_detected']

    def test_escalation_only_when_severity_goes_up(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('landslide', 'medium', 'authority', district_id=world['a'])
            add_evidence(incident, 'medium')  # unchanged
            add_evidence(incident, 'low')  # never lowered automatically
            assert incident.severity == 'medium'
            assert _notes(uid, 'hazard_escalated') == []

            add_evidence(incident, 'high')
            add_evidence(incident, 'high')
            add_evidence(incident, 'critical')
            escalations = _notes(uid, 'hazard_escalated')
            assert sorted(n.severity for n in escalations) == ['critical', 'high']

    def test_authority_lowering_is_silent_and_reraise_is_not_repeated(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            update_event(incident, severity='medium')
            assert _notes(uid, 'hazard_escalated') == []
            update_event(incident, severity='high')
            update_event(incident, severity='medium')
            update_event(incident, severity='high')
            assert len(_notes(uid, 'hazard_escalated')) == 1

    def test_repeated_lifecycle_call_is_deduplicated(self, app, world):
        with app.app_context():
            incident = create_hazard_event('flood', 'medium', 'authority', district_id=world['a'])
            assert notification_service.notify_hazard_detected(incident) == []

    def test_invalid_transition_sends_nothing(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('flood', 'medium', 'authority', district_id=world['a'])
            with pytest.raises(ValueError):
                transition_event_status(incident, 'resolved')
            db.session.rollback()
            assert len(_notes(uid)) == 1

    def test_no_private_data_in_notifications(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            create_hazard_event('landslide', 'high', 'citizen_report', district_id=world['a'],
                                title='Slide near school', description='reported by Ram, phone 98XXXXXXXX',
                                source_reference='user_42')
            note = _notes(uid)[0]
            text = str(note.to_dict())
            assert 'Slide near school' in text
            assert 'user_42' not in text and 'Ram' not in text and 'source_reference' not in text


class TestEarthquake:
    def test_earthquake_detected_and_escalated(self, app, world):
        uid = world['users']['citizen_a']
        with app.app_context():
            incident = create_hazard_event('earthquake', 'medium', 'system', district_id=world['a'],
                                           title='Abnormal ground motion')
            detected = _notes(uid, 'hazard_detected')
            assert len(detected) == 1
            assert detected[0].title == 'Earthquake / abnormal ground motion detected in District A'
            assert incident.confidence is None

            add_evidence(incident, 'critical')
            escalated = _notes(uid, 'hazard_escalated')
            assert len(escalated) == 1
            assert escalated[0].severity == 'critical'
            assert 'escalated to CRITICAL' in escalated[0].title

    def test_authority_can_report_earthquake_via_api(self, app, client, world):
        _login(client, 'auth_a')
        response = client.post('/api/hazards', json={'event_type': 'earthquake', 'severity': 'high'})
        assert response.status_code == 201
        with app.app_context():
            assert len(_notes(world['users']['citizen_a'], 'hazard_detected')) == 1


class TestIoTFloodNotifications:
    def test_flood_sequence_notifies_once_per_state_change(self, app, client, world):
        uid = world['users']['citizen_a']

        def counts():
            with app.app_context():
                return (len(_notes(uid, 'hazard_detected')), len(_notes(uid, 'hazard_escalated')), len(_notes(uid)))

        _telemetry(client, 2.0)  # 50% normal
        assert counts() == (0, 0, 0)
        _telemetry(client, 3.4)  # 85% rising
        assert counts() == (1, 0, 1)
        _telemetry(client, 3.5)  # rising again
        _telemetry(client, 3.6)
        assert counts() == (1, 0, 1)
        _telemetry(client, 4.2)  # flooding
        assert counts() == (1, 1, 2)
        _telemetry(client, 4.5)  # flooding again
        _telemetry(client, 3.4)  # back to rising: severity is not lowered, nothing sent
        assert counts() == (1, 1, 2)

        with app.app_context():
            assert Notification.query.filter_by(type='river_alert').count() == 0  # M01 spam path removed
            assert Incident.query.filter_by(river_id=world['river']).count() == 1
            assert _notes(uid)[0].link == f"/rivers/status?district_id={world['a']}"


class TestNotificationApi:
    def _seed(self, app, world):
        with app.app_context():
            create_hazard_event('landslide', 'high', 'authority', district_id=world['a'])
            create_hazard_event('flood', 'medium', 'authority', district_id=world['b'])
            mine = _notes(world['users']['citizen_a'])[0].id
            theirs = _notes(world['users']['citizen_b'])[0].id
            return mine, theirs

    @pytest.mark.parametrize('method,url', [
        ('get', '/api/notifications'), ('get', '/api/notifications/unread-count'),
        ('post', '/api/notifications/1/read'), ('post', '/api/notifications/read-all'),
    ])
    def test_requires_login(self, client, world, method, url):
        assert getattr(client, method)(url).status_code == 401

    def test_citizen_sees_only_own(self, app, client, world):
        mine, theirs = self._seed(app, world)
        _login(client, 'citizen_a')
        data = client.get('/api/notifications').get_json()
        assert [n['id'] for n in data['notifications']] == [mine]
        assert data['unread_count'] == 1
        assert 'source_reference' not in str(data)
        assert client.get('/api/notifications/unread-count').get_json() == {'unread_count': 1}

    def test_mark_read_and_idor(self, app, client, world):
        mine, theirs = self._seed(app, world)
        _login(client, 'citizen_a')
        assert client.post(f'/api/notifications/{theirs}/read').status_code == 404  # no existence leak
        assert client.post('/api/notifications/999999/read').status_code == 404
        assert client.post('/api/notifications/abc/read').status_code == 400
        response = client.post(f'/api/notifications/{mine}/read')
        assert response.status_code == 200
        assert response.get_json()['notification']['is_read'] is True
        assert response.get_json()['unread_count'] == 0
        with app.app_context():
            assert db.session.get(Notification, theirs).is_read is False
        assert client.get('/api/notifications?unread=1').get_json()['notifications'] == []

    def test_read_all_touches_only_own(self, app, client, world):
        mine, theirs = self._seed(app, world)
        _login(client, 'admin')  # admin receives both hazards
        assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 2
        assert client.post('/api/notifications/read-all').get_json() == {'updated': 2, 'unread_count': 0}
        with app.app_context():
            assert db.session.get(Notification, mine).is_read is False
            assert db.session.get(Notification, theirs).is_read is False

    def test_authority_sees_own_district_hazards(self, app, client, world):
        self._seed(app, world)
        _login(client, 'auth_b')
        titles = [n['title'] for n in client.get('/api/notifications').get_json()['notifications']]
        assert titles == ['Flood detected in District B']

    def test_no_http_endpoint_creates_notifications(self, client, world):
        _login(client, 'admin')
        assert client.post('/api/notifications', json={'user_id': 1, 'title': 'x'}).status_code == 405

    def test_csrf_enforced_when_enabled(self, app, client, world):
        mine, _ = self._seed(app, world)
        _login(client, 'citizen_a')
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            assert client.post(f'/api/notifications/{mine}/read').status_code == 400
            assert client.post('/api/notifications/read-all').status_code == 400
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


class TestNotificationCenterPage:
    def test_page_lists_notifications_with_badge(self, app, client, world):
        with app.app_context():
            create_hazard_event('earthquake', 'critical', 'system', district_id=world['a'])
        _login(client, 'citizen_a')
        client.get('/language/set/en')
        body = client.get('/notifications').get_data(as_text=True)
        assert 'Earthquake / abnormal ground motion detected in District A' in body
        assert 'class="nav-badge"' in body
        assert 'Mark as read' in body
        assert 'badge-danger' in body  # critical severity

        client.get('/language/set/ne')
        assert 'सूचनाहरू' in client.get('/notifications').get_data(as_text=True)

    def test_page_requires_login(self, client, world):
        assert client.get('/notifications').status_code == 302

    def test_empty_state(self, client, world):
        _login(client, 'citizen_b')
        client.get('/language/set/en')
        body = client.get('/notifications').get_data(as_text=True)
        assert 'No notifications yet.' in body
        assert 'class="nav-badge"' not in body
