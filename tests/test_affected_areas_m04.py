"""M04: affected districts, per-user alert dedup, escalation, expansion, API/RBAC, all hazard types."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (Authority, District, Incident, IncidentAffectedDistrict, IoTDevice, Notification,
                        River, User)
from app.services import notification_service
from app.services.hazard_event_service import (
    add_affected_district, add_evidence, create_hazard_event, reject_event, remove_affected_district,
    resolve_event, transition_event_status, update_event,
)


@pytest.fixture
def world(app):
    """Districts A, B, C; one citizen per district; authorities for A and B; an admin; a gauge on A's river."""
    with app.app_context():
        districts = {k: District(name=f'District {k}', province='P') for k in 'ABC'}
        db.session.add_all(districts.values())
        db.session.commit()
        ids = {k: d.id for k, d in districts.items()}
        river = River(name='Narayani', district_id=ids['A'], current_level=1.0, danger_level=4.0, status='normal')
        auth_a = Authority(name='Auth A', category='water', district_id=ids['A'])
        auth_b = Authority(name='Auth B', category='water', district_id=ids['B'])
        db.session.add_all([river, auth_a, auth_b])
        db.session.commit()
        device = IoTDevice(device_id='ESP32-M04', name='Gauge', district_id=ids['A'], river_id=river.id, enabled=True)
        device.api_key_hash = IoTDevice.hash_api_key('k')
        db.session.add(device)
        users = {}
        for username, role, district_id, authority_id in [
            ('citizen_a', 'citizen', ids['A'], None),
            ('citizen_b', 'citizen', ids['B'], None),
            ('citizen_c', 'citizen', ids['C'], None),
            ('auth_a', 'authority', None, auth_a.id),
            ('auth_b', 'authority', ids['B'], auth_b.id),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=username, email=f'{username}@t.np', role=role,
                        district_id=district_id, authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[username] = user
        db.session.commit()
        return {**ids, 'river': river.id, 'u': {k: v.id for k, v in users.items()}}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _types(user_id):
    return sorted(n.type for n in Notification.query.filter_by(user_id=user_id).all())


def _who_got(world, ntype, severity=None):
    query = Notification.query.filter_by(type=ntype)
    if severity:
        query = query.filter_by(severity=severity)
    ids = {n.user_id for n in query}
    return {name for name, uid in world['u'].items() if uid in ids}


def _hazard(world, event_type='flood', severity='medium', district='A'):
    return create_hazard_event(event_type, severity, 'authority', district_id=world[district])


class TestAffectedDistrictModel:
    def test_primary_is_implicit_and_additional_listed_after(self, app, world):
        with app.app_context():
            incident = _hazard(world)
            assert incident.affected_district_ids == [world['A']]
            assert IncidentAffectedDistrict.query.count() == 0  # primary is not stored as a row
            add_affected_district(incident, world['B'])
            assert incident.affected_district_ids == [world['A'], world['B']]
            assert incident.to_dict()['affected_districts'] == [
                {'id': world['A'], 'name': 'District A'}, {'id': world['B'], 'name': 'District B'}]

    def test_database_rejects_duplicate_pair(self, app, world):
        with app.app_context():
            incident = _hazard(world)
            db.session.add(IncidentAffectedDistrict(incident_id=incident.id, district_id=world['B']))
            db.session.commit()
            db.session.add(IncidentAffectedDistrict(incident_id=incident.id, district_id=world['B']))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_service_rejects_unknown_primary_and_duplicate_district(self, app, world):
        with app.app_context():
            incident = _hazard(world)
            with pytest.raises(LookupError):
                add_affected_district(incident, 99999)
            with pytest.raises(ValueError):
                add_affected_district(incident, world['A'])  # primary
            add_affected_district(incident, world['B'])
            with pytest.raises(ValueError):
                add_affected_district(incident, world['B'])
            db.session.rollback()
            assert IncidentAffectedDistrict.query.count() == 1


class TestTargetingAndExpansion:
    def test_only_affected_district_users_are_targeted(self, app, world):
        with app.app_context():
            _hazard(world)
            assert _who_got(world, 'hazard_detected') == {'citizen_a', 'auth_a', 'admin'}

    def test_expansion_notifies_only_newly_covered_users(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            sent = add_affected_district(incident, world['B'])
            assert {n.user_id for n in sent} == {u['citizen_b'], u['auth_b']}
            assert _types(u['citizen_a']) == ['hazard_detected']  # no repeat for A
            assert _types(u['admin']) == ['hazard_detected']
            add_affected_district(incident, world['C'])
            assert _who_got(world, 'hazard_detected') == {'citizen_a', 'citizen_b', 'citizen_c',
                                                         'auth_a', 'auth_b', 'admin'}
            assert Notification.query.filter_by(type='hazard_detected').count() == 6

    def test_escalation_reaches_every_affected_district_once(self, app, world):
        with app.app_context():
            incident = _hazard(world)
            add_affected_district(incident, world['B'])
            add_affected_district(incident, world['C'])
            add_evidence(incident, 'high')
            add_evidence(incident, 'high')
            assert Notification.query.filter_by(type='hazard_escalated').count() == 6
            assert _who_got(world, 'hazard_escalated', 'high') == set(world['u'])

    def test_expanding_a_confirmed_hazard_sends_detected_and_confirmed(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            transition_event_status(incident, 'investigating')
            transition_event_status(incident, 'confirmed')
            add_affected_district(incident, world['B'])
            assert _types(u['citizen_b']) == ['hazard_confirmed', 'hazard_detected']
            assert _types(u['citizen_a']) == ['hazard_confirmed', 'hazard_detected']

    def test_removed_district_stops_receiving_but_keeps_history(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            add_affected_district(incident, world['B'])
            remove_affected_district(incident, world['B'])
            assert incident.status == 'detected'
            add_evidence(incident, 'critical')
            assert _types(u['citizen_b']) == ['hazard_detected']  # history kept, no escalation
            assert 'hazard_escalated' in _types(u['citizen_a'])
            with pytest.raises(ValueError):
                remove_affected_district(incident, world['A'])
            with pytest.raises(LookupError):
                remove_affected_district(incident, world['C'])

    def test_resolved_hazard_sends_no_new_active_alerts(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            add_affected_district(incident, world['B'])
            transition_event_status(incident, 'investigating')
            transition_event_status(incident, 'confirmed')
            resolve_event(incident)
            assert _who_got(world, 'hazard_resolved') == {'citizen_a', 'citizen_b', 'auth_a', 'auth_b', 'admin'}
            add_affected_district(incident, world['C'])  # kept for history, silent
            update_event(incident, severity='critical')
            assert _types(u['citizen_c']) == []
            assert Notification.query.filter_by(type='hazard_escalated').count() == 0
            assert incident.affected_district_ids == [world['A'], world['B'], world['C']]

    def test_rejected_hazard_sends_no_alerts_and_keeps_areas(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            add_affected_district(incident, world['B'])
            reject_event(incident, 'false alarm')
            add_affected_district(incident, world['C'])
            assert _types(u['citizen_c']) == []
            assert len(incident.affected_district_ids) == 3


class TestDeduplication:
    def test_same_user_event_type_severity_gives_exactly_one(self, app, world):
        with app.app_context():
            incident = _hazard(world)
            for _ in range(3):
                notification_service.notify_hazard_detected(incident)
            assert Notification.query.filter_by(user_id=world['u']['citizen_a']).count() == 1

    def test_escalation_ladder(self, app, world):
        uid = world['u']['citizen_a']
        with app.app_context():
            incident = _hazard(world, severity='medium')
            add_evidence(incident, 'high')      # medium -> high: alert
            add_evidence(incident, 'high')      # high -> high: nothing
            add_evidence(incident, 'critical')  # high -> critical: alert
            update_event(incident, severity='high')  # authority lowers: silent
            update_event(incident, severity='critical')  # back up: already alerted at critical
            got = [(n.type, n.severity) for n in Notification.query.filter_by(user_id=uid).order_by(Notification.id)]
            assert got == [('hazard_detected', 'medium'), ('hazard_escalated', 'high'),
                           ('hazard_escalated', 'critical')]

    def test_database_is_final_defence(self, app, world):
        uid = world['u']['citizen_a']
        with app.app_context():
            incident = _hazard(world)
            db.session.add(Notification(user_id=uid, type='hazard_detected', title='dup',
                                        incident_id=incident.id, dedup_key=f'{incident.id}:hazard_detected'))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_duplicate_in_a_batch_is_skipped_without_losing_the_rest(self, app, world):
        u = world['u']
        with app.app_context():
            incident = _hazard(world)
            key = f'{incident.id}:hazard_confirmed'
            batch = [notification_service._build(u[name], 'hazard_confirmed', 't', incident_id=incident.id,
                                                 dedup_key=key) for name in ('citizen_a', 'citizen_a', 'admin')]
            incident.title = 'kept'
            saved = notification_service._save(batch)
            db.session.commit()
            assert len(saved) == 2
            assert Notification.query.filter_by(dedup_key=key).count() == 2
            assert db.session.get(Incident, incident.id).title == 'kept'

    def test_legacy_notifications_without_key_are_not_constrained(self, app, world):
        uid = world['u']['citizen_a']
        with app.app_context():
            for _ in range(2):
                db.session.add(Notification(user_id=uid, type='river_alert', title='legacy'))
            db.session.commit()
            assert Notification.query.filter_by(type='river_alert').count() == 2


@pytest.mark.parametrize('event_type', ['flood', 'earthquake', 'landslide', 'road_damage'])
def test_every_hazard_type_uses_the_same_pipeline(app, world, event_type):
    with app.app_context():
        incident = _hazard(world, event_type=event_type, severity='low')
        add_affected_district(incident, world['B'])
        add_evidence(incident, 'critical')
        add_evidence(incident, 'critical')
        assert _who_got(world, 'hazard_detected') == {'citizen_a', 'citizen_b', 'auth_a', 'auth_b', 'admin'}
        assert Notification.query.filter_by(type='hazard_escalated').count() == 5
        from app.services.hazard_event_service import get_event_statistics
        assert get_event_statistics()['by_type'][event_type] == 1


class TestIoTFloodWithAffectedAreas:
    def _read(self, client, level):
        assert client.post('/api/iot/telemetry', headers={'Authorization': 'Bearer ESP32-M04:k'},
                           json={'readings': [{'sensor_type': 'water_level', 'value': level, 'unit': 'm'}]}
                           ).status_code == 201

    def test_rising_flooding_across_two_districts(self, app, client, world):
        u = world['u']
        self._read(client, 3.4)  # rising -> event in A
        with app.app_context():
            event_id = Incident.query.filter_by(river_id=world['river']).one().id
        _login(client, 'auth_a')
        assert client.post(f'/api/hazards/{event_id}/affected-districts',
                           json={'district_id': world['B']}).status_code == 201
        for level in (3.5, 3.6, 3.5):  # repeated rising
            self._read(client, level)
        self._read(client, 4.2)  # flooding
        self._read(client, 4.6)  # repeated flooding
        with app.app_context():
            for name in ('citizen_a', 'citizen_b'):
                assert _types(u[name]) == ['hazard_detected', 'hazard_escalated'], name
            assert _types(u['citizen_c']) == []
            assert Incident.query.count() == 1


class TestAffectedDistrictApi:
    def _event(self, app, world):
        with app.app_context():
            return _hazard(world).id

    def test_requires_login(self, app, client, world):
        event_id = self._event(app, world)
        url = f'/api/hazards/{event_id}/affected-districts'
        assert client.get(url).status_code == 401
        assert client.post(url, json={'district_id': world['B']}).status_code == 401
        assert client.delete(f"{url}/{world['B']}").status_code == 401

    def test_citizen_can_view_but_not_modify(self, app, client, world):
        event_id = self._event(app, world)
        _login(client, 'citizen_c')
        url = f'/api/hazards/{event_id}/affected-districts'
        response = client.get(url)
        assert response.status_code == 200
        assert response.get_json()['affected_districts'] == [{'id': world['A'], 'name': 'District A'}]
        assert client.post(url, json={'district_id': world['C']}).status_code == 403
        assert client.delete(f"{url}/{world['A']}").status_code == 403

    def test_authority_manages_only_own_hazards(self, app, client, world):
        event_id = self._event(app, world)
        url = f'/api/hazards/{event_id}/affected-districts'
        _login(client, 'auth_b')
        assert client.post(url, json={'district_id': world['B']}).status_code == 403
        _login(client, 'auth_a')
        response = client.post(url, json={'district_id': world['B']})
        assert response.status_code == 201
        body = response.get_json()
        assert [d['id'] for d in body['affected_districts']] == [world['A'], world['B']]
        assert body['notifications_sent'] == 2  # citizen_b, auth_b
        _login(client, 'auth_b')
        assert client.delete(f"{url}/{world['B']}").status_code == 403

    def test_admin_manages_any_hazard(self, app, client, world):
        event_id = self._event(app, world)
        url = f'/api/hazards/{event_id}/affected-districts'
        _login(client, 'admin')
        assert client.post(url, json={'district_id': world['C']}).status_code == 201
        response = client.delete(f"{url}/{world['C']}")
        assert response.status_code == 200
        assert [d['id'] for d in response.get_json()['affected_districts']] == [world['A']]
        with app.app_context():
            assert len(_types(world['u']['citizen_c'])) == 1  # historical alert kept

    def test_validation(self, app, client, world):
        event_id = self._event(app, world)
        url = f'/api/hazards/{event_id}/affected-districts'
        _login(client, 'admin')
        assert client.post(url, json={'district_id': str(world['B'])}).status_code == 400
        assert client.post(url, json={'district_id': True}).status_code == 400
        assert client.post(url, json={}).status_code == 400
        assert client.post(url, json=[world['B']]).status_code == 400
        assert client.post(url, data='{bad', content_type='application/json').status_code == 400
        assert client.post(url, json={'district_name': 'District B'}).status_code == 400
        assert client.post(url, json={'district_id': 99999}).status_code == 404
        assert client.post(url, json={'district_id': world['A']}).status_code == 409  # primary
        assert client.post(url, json={'district_id': world['B']}).status_code == 201
        assert client.post(url, json={'district_id': world['B']}).status_code == 409  # duplicate
        assert client.post('/api/hazards/99999/affected-districts', json={'district_id': world['B']}).status_code == 404
        assert client.get('/api/hazards/99999/affected-districts').status_code == 404
        assert client.delete(f"{url}/{world['A']}").status_code == 400  # primary
        assert client.delete(f"{url}/{world['C']}").status_code == 404  # not attached

    def test_csrf_enforced(self, app, client, world):
        event_id = self._event(app, world)
        url = f'/api/hazards/{event_id}/affected-districts'
        _login(client, 'admin')
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            assert client.post(url, json={'district_id': world['B']}).status_code == 400
            assert client.delete(f"{url}/{world['A']}").status_code == 400
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_hazard_payloads_and_district_views_include_additional_districts(self, app, client, world):
        event_id = self._event(app, world)
        with app.app_context():
            add_affected_district(db.session.get(Incident, event_id), world['B'])
        _login(client, 'citizen_b')
        event = client.get(f'/api/hazards/{event_id}').get_json()
        assert [d['name'] for d in event['affected_districts']] == ['District A', 'District B']
        assert 'source_reference' not in event
        active_b = client.get(f"/api/hazards/district/{world['B']}/active").get_json()['events']
        assert [e['id'] for e in active_b] == [event_id]
        listed = client.get(f"/api/hazards?district_id={world['B']}").get_json()['events']
        assert [e['id'] for e in listed] == [event_id]
        assert client.get(f"/api/hazards?district_id={world['C']}").get_json()['events'] == []

        note = client.get('/api/notifications').get_json()['notifications'][0]
        assert note['hazard']['affected_districts'] == ['District A', 'District B']
        assert note['hazard']['district_name'] == 'District A'
        assert 'dedup_key' not in note and 'source_reference' not in str(note)


def test_notification_center_shows_areas_and_relative_time(app, client, world):
    with app.app_context():
        incident = _hazard(world, event_type='earthquake', severity='critical')
        add_affected_district(incident, world['B'])
    _login(client, 'citizen_b')
    client.get('/language/set/en')
    body = client.get('/notifications').get_data(as_text=True)
    assert 'District A, District B' in body
    assert 'class="rel-time"' in body
    assert 'Earthquake / abnormal ground motion detected in District A' in body
