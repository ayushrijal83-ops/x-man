"""M10: security/reliability hardening — regression tests for every finding fixed in M10, plus the
cross-district authorization matrix over IoT, hazards, M09, reports and notifications."""
import io
import os
import subprocess
import sys

import pytest
from PIL import Image

from app import create_app
from app.config import ProductionConfig
from app.extensions import db
from app.models import (Authority, CitizenReport, Complaint, District, Incident, IoTDevice, Notification,
                        Project, River, RoadSegment, User)
from app.models.iot_device import SensorReading
from app.services import dashboard_service
from app.services.hazard_event_service import create_hazard_event
from app.services.risk_engine import validate_sensor_reading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def world(app, tmp_path):
    app.config['REPORT_UPLOAD_DIR'] = str(tmp_path / 'reports')
    with app.app_context():
        a, b = District(name='District A', province='P'), District(name='District B', province='P')
        db.session.add_all([a, b])
        db.session.commit()
        auth_a = Authority(name='Auth A', category='roads', district_id=a.id)
        auth_b = Authority(name='Auth B', category='roads', district_id=b.id)
        db.session.add_all([auth_a, auth_b])
        db.session.commit()
        users = {}
        for name, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None), ('citizen_b', 'citizen', b.id, None),
            ('auth_a', 'authority', a.id, auth_a.id), ('auth_b', 'authority', b.id, auth_b.id),
            ('auth_unlinked', 'authority', a.id, None), ('admin', 'admin', None, None),
        ]:
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district_id,
                        authority_id=authority_id, phone='9800000000')
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        db.session.commit()
        river_a = River(name='River A', district_id=a.id, current_level=1.0, danger_level=4.0, status='normal')
        river_b = River(name='River B', district_id=b.id, current_level=1.0, danger_level=4.0, status='normal')
        road_b = RoadSegment(name='Road B', district_id=b.id, status='open')
        project_a = Project(name='Bridge A', district_id=a.id, authority_id=auth_a.id, progress_percent=10)
        db.session.add_all([river_a, river_b, road_b, project_a])
        db.session.commit()
        devices = {}
        for key, district, authority in [('DEV-A', a, auth_a), ('DEV-B', b, auth_b), ('DEV-ORPHAN', a, None)]:
            device = IoTDevice(device_id=key, name=key, district_id=district.id,
                               authority_id=authority.id if authority else None,
                               api_key_hash=IoTDevice.hash_api_key(f'key-{key}'), enabled=True,
                               river_id=river_a.id if key == 'DEV-A' else None)
            db.session.add(device)
            devices[key] = device
        complaint = Complaint(ticket_number='T-1', user_id=users['citizen_a'].id, authority_id=auth_a.id,
                              district_id=a.id, category='roads', description='PRIVATE complaint text',
                              status='pending')
        db.session.add(complaint)
        db.session.commit()
        hazard_a = create_hazard_event('flood', 'high', 'authority', district_id=a.id)
        hazard_b = create_hazard_event('landslide', 'medium', 'authority', district_id=b.id)
        return {'a': a.id, 'b': b.id, 'u': {k: v.id for k, v in users.items()},
                'd': {k: v.id for k, v in devices.items()}, 'river_a': river_a.id, 'river_b': river_b.id,
                'road_b': road_b.id, 'project_a': project_a.id, 'complaint': complaint.id,
                'hazard_a': hazard_a.id, 'hazard_b': hazard_b.id}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _telemetry(client, device, body, key=None):
    return client.post('/api/iot/telemetry', json=body,
                       headers={'Authorization': f"Bearer {device}:{key or f'key-{device}'}"})


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (32, 24), (90, 90, 90)).save(buf, format='JPEG')
    return buf.getvalue()


# ======================================================================= IoT device authorization

class TestDeviceAuthorization:
    @pytest.mark.parametrize('query', ['', '?district_id=1', '?district_id=2'])
    def test_unlinked_authority_cannot_list_devices(self, client, world, query):
        _login(client, 'auth_unlinked')
        response = client.get('/api/iot/devices' + query)
        assert response.status_code == 403
        assert 'devices' not in response.get_json()

    def test_device_list_scope(self, client, world):
        _login(client, 'citizen_a')
        assert client.get('/api/iot/devices').status_code == 403
        _login(client, 'auth_a')
        listed = client.get(f"/api/iot/devices?district_id={world['b']}").get_json()['devices']
        assert [d['device_id'] for d in listed] == ['DEV-A']  # district_id can't widen an authority's scope
        _login(client, 'admin')
        assert len(client.get('/api/iot/devices').get_json()['devices']) == 3
        assert [d['device_id'] for d in client.get(f"/api/iot/devices?district_id={world['b']}")
                .get_json()['devices']] == ['DEV-B']
        assert client.get('/api/iot/devices?district_id=abc').status_code == 400
        body = client.get('/api/iot/devices').get_data(as_text=True)
        for secret in ('api_key_hash', 'key-DEV', IoTDevice.hash_api_key('key-DEV-A')):
            assert secret not in body

    @pytest.mark.parametrize('who, device, expected', [
        ('auth_unlinked', 'DEV-ORPHAN', 403),  # was allowed: None != None is False
        ('auth_unlinked', 'DEV-A', 403),
        ('auth_b', 'DEV-A', 403), ('auth_a', 'DEV-B', 403), ('auth_a', 'DEV-ORPHAN', 403),
        ('citizen_a', 'DEV-A', 403),
        ('auth_a', 'DEV-A', 200), ('admin', 'DEV-B', 200), ('admin', 'DEV-ORPHAN', 200),
    ])
    def test_update_and_rotate_ownership(self, app, client, world, who, device, expected):
        _login(client, who)
        device_pk = world['d'][device]
        assert client.patch(f'/api/iot/devices/{device_pk}', json={'status': 'maintenance'}).status_code == expected
        assert client.post(f'/api/iot/devices/{device_pk}/rotate-key').status_code == expected
        with app.app_context():
            row = db.session.get(IoTDevice, device_pk)
            key_unchanged = row.api_key_hash == IoTDevice.hash_api_key(f'key-{device}')
            assert key_unchanged == (expected != 200)

    def test_unknown_device_is_json_404(self, client, world):
        _login(client, 'admin')
        for response in (client.patch('/api/iot/devices/9999', json={'enabled': False}),
                         client.post('/api/iot/devices/9999/rotate-key')):
            assert response.status_code == 404 and response.get_json() == {'error': 'Not found'}

    def test_key_rotation_takes_effect_immediately(self, client, world):
        reading = {'readings': [{'sensor_type': 'temperature', 'value': 21.5, 'unit': '°C'}]}
        assert _telemetry(client, 'DEV-A', reading).status_code == 201
        _login(client, 'auth_a')
        body = client.post(f"/api/iot/devices/{world['d']['DEV-A']}/rotate-key").get_json()
        new_key = body['api_key']
        assert 'api_key_hash' not in body
        assert _telemetry(client, 'DEV-A', reading).status_code == 401  # old key dead
        assert _telemetry(client, 'DEV-A', reading, key=new_key).status_code == 201
        assert _telemetry(client, 'DEV-B', reading, key=new_key).status_code == 401  # can't impersonate

    def test_disabled_device_rejected(self, client, world):
        _login(client, 'auth_a')
        assert client.patch(f"/api/iot/devices/{world['d']['DEV-A']}", json={'enabled': False}).status_code == 200
        reading = {'readings': [{'sensor_type': 'temperature', 'value': 21.5, 'unit': '°C'}]}
        assert _telemetry(client, 'DEV-A', reading).status_code == 401


class TestDeviceInput:
    def test_register_with_river_works(self, app, client, world):
        _login(client, 'auth_a')  # was a 500 NameError (River not imported)
        response = client.post('/api/iot/devices', json={'device_id': 'NEW-1', 'name': 'Gauge',
                                                         'district_id': world['a'], 'river_id': world['river_a'],
                                                         'latitude': 27.1, 'longitude': 85.2})
        assert response.status_code == 201
        assert response.get_json()['device']['river_id'] == world['river_a']

    @pytest.mark.parametrize('body', [
        {'device_id': 'BAD:ID', 'name': 'x'}, {'device_id': '../x', 'name': 'x'}, {'device_id': 'x' * 65, 'name': 'x'},
        {'device_id': ['x'], 'name': 'x'}, {'device_id': 'OK-1', 'name': {'a': 1}},
        {'device_id': 'OK-1', 'name': 'x', 'district_id': '1'}, {'device_id': 'OK-1', 'name': 'x', 'district_id': True},
        {'device_id': 'OK-1', 'name': 'x', 'latitude': 91, 'longitude': 85},
        {'device_id': 'OK-1', 'name': 'x', 'latitude': 27},
        {'device_id': 'OK-1', 'name': 'x', 'river_id': 'abc'},
        {'device_id': 'OK-1', 'name': 'x', 'description': 'd' * 1001},
    ])
    def test_register_rejects_bad_input(self, app, client, world, body):
        _login(client, 'admin')
        body = {'district_id': world['a'], **body}
        assert client.post('/api/iot/devices', json=body).status_code == 400
        with app.app_context():
            assert IoTDevice.query.count() == 3

    def test_authority_cannot_register_into_other_district(self, client, world):
        _login(client, 'auth_a')
        assert client.post('/api/iot/devices', json={'device_id': 'X-1', 'name': 'x',
                                                     'district_id': world['b']}).status_code == 403

    @pytest.mark.parametrize('body', [
        {'enabled': 'false'}, {'enabled': 0}, {'status': 'hacked'}, {'api_key_hash': 'x'},
        {'authority_id': 2}, {'district_id': 2}, {'device_id': 'X'}, {'latitude': 27.0},
        {'latitude': 'a', 'longitude': 'b'}, {'firmware_version': ['1']}, {'river_id': 999}, {},
    ])
    def test_update_rejects_bad_or_forbidden_fields(self, app, client, world, body):
        _login(client, 'auth_a')
        assert client.patch(f"/api/iot/devices/{world['d']['DEV-A']}", json=body).status_code == 400
        with app.app_context():
            device = db.session.get(IoTDevice, world['d']['DEV-A'])
            assert (device.enabled, device.status, device.authority_id is not None) == (True, 'active', True)


# ======================================================================= telemetry validation

def _raw(client, device, raw):
    return client.post('/api/iot/telemetry', data=raw, content_type='application/json',
                       headers={'Authorization': f'Bearer {device}:key-{device}'})


class TestTelemetryValidation:
    @pytest.mark.parametrize('raw', [
        '{"readings":[{"sensor_type":"water_level","value":NaN,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":Infinity,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":-Infinity,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":1e999,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":true,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":"3.3","unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":[3.3],"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":{"v":3.3},"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":null,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":-1,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"water_level","value":330,"unit":"cm"}]}',
        '{"readings":[{"sensor_type":["water_level"],"value":3.3,"unit":"m"}]}',
        '{"readings":[{"sensor_type":"radiation","value":3.3,"unit":"Sv"}]}',
        '{"readings":[{"sensor_type":"water_level","value":3.3,"unit":7}]}',
        '{"readings":["water_level"]}', '{"readings":[3.3]}', '{"readings":{}}', '{"readings":[]}',
        '[{"sensor_type":"water_level","value":3.3,"unit":"m"}]', '"text"', 'null', '{not json',
    ])
    def test_invalid_payloads_rejected_without_storage(self, app, client, world, raw):
        response = _raw(client, 'DEV-A', raw)
        assert response.status_code == 400
        assert response.is_json
        with app.app_context():
            assert SensorReading.query.count() == 0 and Incident.query.filter_by(event_type='flood').count() == 1

    def test_too_many_readings(self, client, world):
        body = {'readings': [{'sensor_type': 'temperature', 'value': 20, 'unit': '°C'}] * 51}
        assert _telemetry(client, 'DEV-A', body).status_code == 400

    @pytest.mark.parametrize('timestamp', [12345, {'t': 1}, ['2026-10-01'], 'yesterday', '2026-13-45T99:00:00',
                                           '2026-10-01T10:00:00+25:00', 'x' * 100])
    def test_malformed_timestamps(self, app, client, world, timestamp):
        body = {'timestamp': timestamp, 'readings': [{'sensor_type': 'temperature', 'value': 20, 'unit': '°C'}]}
        response = _telemetry(client, 'DEV-A', body)
        assert response.status_code == 400 and response.is_json
        with app.app_context():
            assert SensorReading.query.count() == 0

    @pytest.mark.parametrize('timestamp, stored', [
        ('2026-10-01T10:00:00Z', '2026-10-01 10:00:00'),
        ('2026-10-01T15:45:00+05:45', '2026-10-01 10:00:00'),  # Nepal time -> naive UTC
        ('2026-10-01T10:00:00', '2026-10-01 10:00:00'),        # naive treated as UTC
    ])
    def test_valid_timestamps_normalized_to_naive_utc(self, app, client, world, timestamp, stored):
        body = {'timestamp': timestamp, 'readings': [{'sensor_type': 'temperature', 'value': 20, 'unit': '°C'}]}
        assert _telemetry(client, 'DEV-A', body).status_code == 201
        with app.app_context():
            reading = SensorReading.query.one()
            assert reading.recorded_at.tzinfo is None and str(reading.recorded_at) == stored

    def test_validator_rejects_non_finite_directly(self):
        for value in (float('nan'), float('inf'), True, '3'):
            assert validate_sensor_reading('water_level', value, 'm')[0] is False
        assert validate_sensor_reading('water_level', 3, 'm') == (True, None)

    def test_latest_limit_cannot_be_disabled(self, app, client, world):
        _telemetry(client, 'DEV-A', {'readings': [{'sensor_type': 'temperature', 'value': 20, 'unit': '°C'},
                                                  {'sensor_type': 'humidity', 'value': 70, 'unit': '%'},
                                                  {'sensor_type': 'water_level', 'value': 1.0, 'unit': 'm'}]})
        _login(client, 'admin')
        assert client.get('/api/iot/latest?limit=-1').get_json()['count'] == 1  # LIMIT -1 was "no limit"
        assert client.get('/api/iot/latest?limit=2').get_json()['count'] == 2


# ======================================================================= authority panel / legacy IDOR

class TestObjectLevelAuthorization:
    def test_complaint_detail_scoped(self, app, client, world):
        url = f"/complaints/{world['complaint']}"
        for who, code in [('citizen_b', 404), ('auth_b', 404), ('citizen_a', 200), ('auth_a', 200), ('admin', 200)]:
            _login(client, who)
            response = client.get(url)
            assert response.status_code == code
            assert ('PRIVATE complaint text' in response.get_data(as_text=True)) == (code == 200)

    def test_panel_complaint_scoped_to_authority(self, app, client, world):
        url = f"/authority/complaints/{world['complaint']}"
        _login(client, 'auth_b')
        assert client.get(url).status_code == 404
        assert client.post(url, data={'response': 'hijack', 'status': 'resolved'}).status_code == 404
        _login(client, 'auth_a')
        assert client.get(url).status_code == 200
        client.post(url, data={'response': 'x', 'status': 'bogus'})  # invalid status: no change
        with app.app_context():
            complaint = db.session.get(Complaint, world['complaint'])
            assert (complaint.status, complaint.government_response) == ('pending', None)
        client.post(url, data={'response': 'On it', 'status': 'in_progress'})
        with app.app_context():
            assert db.session.get(Complaint, world['complaint']).status == 'in_progress'

    def test_panel_road_river_project_scoped(self, app, client, world):
        _login(client, 'auth_a')
        assert client.post(f"/authority/roads/{world['road_b']}/update",
                           data={'status': 'blocked', 'traffic_level': 'severe'}).status_code == 404
        assert client.post(f"/authority/rivers/{world['river_b']}/update", data={'water_level': '9'}).status_code == 404
        _login(client, 'auth_b')
        assert client.post(f"/authority/projects/{world['project_a']}/update",
                           data={'progress_percent': '100'}).status_code == 404
        with app.app_context():
            assert db.session.get(RoadSegment, world['road_b']).status == 'open'
            assert db.session.get(River, world['river_b']).current_level == 1.0
            assert db.session.get(Project, world['project_a']).progress_percent == 10

    @pytest.mark.parametrize('level', ['nan', 'inf', '-1', '51', 'abc'])
    def test_panel_river_level_validated(self, app, client, world, level):
        _login(client, 'auth_a')
        client.post(f"/authority/rivers/{world['river_a']}/update", data={'water_level': level, 'status': 'rising'})
        with app.app_context():
            assert db.session.get(River, world['river_a']).current_level == 1.0

    def test_public_update_routes_need_scoped_manager(self, app, client, world):
        _login(client, 'citizen_a')  # both used to be open to any logged-in user
        assert client.post(f"/projects/{world['project_a']}/update", data={'progress_percent': '100'}).status_code == 403
        assert client.post(f"/rivers/{world['river_a']}/update", data={'water_level': '4.5'}).status_code == 403
        _login(client, 'auth_b')
        assert client.post(f"/rivers/{world['river_a']}/update", data={'water_level': '4.5'}).status_code == 403
        with app.app_context():
            assert db.session.get(River, world['river_a']).current_level == 1.0
        _login(client, 'auth_a')
        client.post(f"/rivers/{world['river_a']}/update", data={'water_level': '3.3'})
        with app.app_context():
            river = db.session.get(River, world['river_a'])
            assert (river.current_level, river.status) == (3.3, 'rising')  # M01: 82.5% = rising (was 'high')


# ======================================================================= cross-district matrix

class TestAuthorizationMatrix:
    """Resource x role: who can read/manage what (documented in PROJECT_PROGRESS M10)."""

    @pytest.fixture
    def report_id(self, client, world):
        _login(client, 'citizen_a')
        response = client.post('/api/reports', content_type='multipart/form-data', data={
            'hazard_type': 'landslide', 'district_id': str(world['a']), 'description': 'PRIVATE report text',
            'image': (io.BytesIO(_jpeg()), 'x.jpg', 'image/jpeg')})
        assert response.status_code == 201
        return response.get_json()['report']['id']

    @pytest.mark.parametrize('who, hazard, expected', [
        ('citizen_a', 'hazard_a', 403), ('citizen_a', 'hazard_b', 403),
        ('auth_a', 'hazard_a', 200), ('auth_a', 'hazard_b', 403),
        ('auth_b', 'hazard_a', 403), ('auth_b', 'hazard_b', 200),
        ('auth_unlinked', 'hazard_a', 403), ('admin', 'hazard_a', 200), ('admin', 'hazard_b', 200),
    ])
    def test_hazard_management_and_m09(self, client, world, who, hazard, expected):
        _login(client, who)
        event_id = world[hazard]
        assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'investigating'}).status_code == expected
        assert client.post(f'/api/hazards/{event_id}/investigations', json={'note': 'n'}).status_code in \
            ((201,) if expected == 200 else (expected,))
        assert client.get(f'/api/hazards/{event_id}/status-history').status_code == expected
        assert client.get(f'/api/hazards/{event_id}/assessment').status_code == expected
        assert client.patch(f'/api/hazards/{event_id}', json={'severity': 'critical'}).status_code == expected

    def test_public_hazard_reads_are_scoped_payloads(self, client, world):
        _login(client, 'citizen_b')
        event = client.get(f"/api/hazards/{world['hazard_a']}").get_json()
        assert 'source_reference' not in event
        assert world['hazard_a'] not in [h['id'] for h in client.get('/api/dashboard').get_json()['hazards']]

    @pytest.mark.parametrize('who, expected', [('citizen_a', 200), ('citizen_b', 404), ('auth_a', 200),
                                               ('auth_b', 404), ('auth_unlinked', 404), ('admin', 200)])
    def test_private_report_and_image(self, client, world, report_id, who, expected):
        _login(client, who)
        detail = client.get(f'/api/reports/{report_id}')
        image = client.get(f'/api/reports/{report_id}/image')
        assert (detail.status_code, image.status_code) == (expected, expected)
        image.close()
        if expected == 404:
            assert 'PRIVATE report text' not in detail.get_data(as_text=True)

    def test_notification_ownership(self, app, client, world):
        with app.app_context():
            other = Notification.query.filter_by(user_id=world['u']['citizen_b']).first()
            own = Notification.query.filter_by(user_id=world['u']['citizen_a']).count()
        _login(client, 'citizen_a')
        assert client.post(f'/api/notifications/{other.id}/read').status_code == 404
        listed = client.get('/api/notifications').get_json()
        assert len(listed['notifications']) == own and listed['unread_count'] == own
        client.post('/api/notifications/read-all')
        with app.app_context():
            assert not db.session.get(Notification, other.id).is_read  # other user's untouched


# ======================================================================= accounts / auth flows

class TestAccounts:
    def test_authority_self_registration_off_by_default(self, app, client, world):
        assert app.config['AUTHORITY_SELF_REGISTRATION'] is False
        assert client.get('/auth/authority/register').status_code == 302
        client.post('/auth/authority/register', data={
            'username': 'intruder', 'email': 'i@x.np', 'password': 'pw', 'authority_name': 'Fake',
            'authority_category': 'water', 'district_id': str(world['a'])})
        with app.app_context():
            assert User.query.filter_by(username='intruder').count() == 0
        assert '/auth/authority/register' not in client.get('/auth/authority/login').get_data(as_text=True)

    def test_authority_self_registration_when_enabled(self, app, client, world):
        app.config['AUTHORITY_SELF_REGISTRATION'] = True
        assert client.get('/auth/authority/register').status_code == 200
        assert '/auth/authority/register' in client.get('/auth/authority/login').get_data(as_text=True)

    @pytest.mark.parametrize('target, allowed', [
        ('https://evil.example/x', False), ('//evil.example', False), ('/\\evil.example', False),
        ('javascript:alert(1)', False), ('/reports/mine', True),
    ])
    def test_login_next_is_same_site_only(self, client, world, target, allowed):
        response = client.post('/auth/login', query_string={'next': target},
                               data={'username': 'citizen_a', 'password': 'pw'})
        assert response.status_code == 302
        location = response.headers['Location']
        assert (location == target) == allowed
        if not allowed:
            assert 'evil' not in location and 'javascript' not in location

    def test_profile_contact_details_private(self, client, world):
        url = f"/profile/{world['u']['citizen_a']}"
        _login(client, 'citizen_b')
        assert 'citizen_a@t.np' not in client.get(url).get_data(as_text=True)
        _login(client, 'citizen_a')
        assert 'citizen_a@t.np' in client.get(url).get_data(as_text=True)
        _login(client, 'admin')
        assert 'citizen_a@t.np' in client.get(url).get_data(as_text=True)

    def test_profile_bad_district_rejected(self, app, client, world):
        _login(client, 'citizen_a')
        for value in ('abc', '99999', '1;DROP'):
            client.post('/profile/edit', data={'district_id': value})
        with app.app_context():
            assert db.session.get(User, world['u']['citizen_a']).district_id == world['a']


# ======================================================================= XSS (frontend sinks)

class TestXss:
    @pytest.mark.parametrize('template, forbidden', [
        ('ai_assistant.html', ["+ question +", "+ response +", "+ msg +"]),
        ('create_post.html', ['data.category ||', "previewText.innerHTML"]),
        ('test_classify.html', ["+ content +", "data.category || 'N/A') + '"]),
    ])
    def test_model_and_user_text_never_reach_innerhtml(self, template, forbidden):
        source = open(os.path.join(REPO, 'app', 'templates', 'pages', template), encoding='utf-8').read()
        for line in source.splitlines():
            if 'innerHTML' in line:
                assert not any(token in line for token in forbidden), line
        assert 'textContent' in source or 'createTextNode' in source


# ======================================================================= CSRF

class TestCsrf:
    @pytest.fixture
    def csrf_client(self, app, world):
        app.config['WTF_CSRF_ENABLED'] = True
        return app.test_client()

    def test_session_writes_need_token_device_api_does_not(self, app, csrf_client, world):
        client = csrf_client
        # telemetry is device-authenticated (API key), so it is exempt and must work
        reading = {'readings': [{'sensor_type': 'temperature', 'value': 20, 'unit': '°C'}]}
        assert _telemetry(client, 'DEV-A', reading).status_code == 201
        page = client.get('/auth/authority/login').get_data(as_text=True)
        token = page.split('name="csrf_token" value="')[1].split('"')[0] if 'name="csrf_token"' in page else \
            page.split('name="csrf-token" content="')[1].split('"')[0]
        client.post('/auth/authority/login', data={'username': 'auth_a', 'password': 'pw', 'csrf_token': token})
        hazard = world['hazard_a']
        for method, url, body in [('post', f'/api/hazards/{hazard}/status', {'status': 'investigating'}),
                                  ('post', f'/api/hazards/{hazard}/investigations', {'note': 'x'}),
                                  ('patch', f'/api/hazards/{hazard}', {'severity': 'critical'}),
                                  ('post', '/api/notifications/read-all', {}),
                                  ('post', f"/api/iot/devices/{world['d']['DEV-A']}/rotate-key", {})]:
            response = getattr(client, method)(url, json=body)
            assert response.status_code == 400 and 'CSRF' in response.get_json()['error'], url
        assert client.post(f'/api/hazards/{hazard}/status', json={'status': 'investigating'},
                           headers={'X-CSRFToken': token}).status_code == 200
        with app.app_context():
            assert db.session.get(Incident, hazard).severity == 'high'


# ======================================================================= errors / headers / config

class TestErrorsAndHeaders:
    def test_api_errors_are_json_without_internals(self, app, client, world, monkeypatch):
        _login(client, 'admin')
        assert client.get('/api/does-not-exist').get_json()['error']
        assert client.delete('/api/dashboard').status_code == 405 and client.delete('/api/dashboard').is_json

        def boom(*args, **kwargs):
            raise RuntimeError(r'C:\secret\path sqlite:///prod.db SECRET_KEY=abc')
        monkeypatch.setattr(dashboard_service, 'build', boom)
        app.config['PROPAGATE_EXCEPTIONS'] = False
        response = client.get('/api/dashboard')
        assert response.status_code == 500 and response.get_json() == {'error': 'Internal server error'}
        body = response.get_data(as_text=True)
        for leak in ('secret', 'sqlite', 'SECRET_KEY', 'Traceback', 'RuntimeError'):
            assert leak not in body

    def test_security_headers(self, client, world):
        response = client.get('/auth/login')
        headers = response.headers
        assert headers['X-Content-Type-Options'] == 'nosniff'
        assert headers['X-Frame-Options'] == 'SAMEORIGIN'
        assert headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
        assert 'geolocation=(self)' in headers['Permissions-Policy'] and 'camera=(self)' in headers['Permissions-Policy']
        csp = headers['Content-Security-Policy']
        for directive in ("default-src 'self'", "object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'",
                          'https://unpkg.com', 'https://*.tile.openstreetmap.org'):
            assert directive in csp

    def test_production_refuses_default_secret(self, monkeypatch):
        monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'dev-key-change-me')
        with pytest.raises(RuntimeError, match='SECRET_KEY'):
            create_app('production')
        assert ProductionConfig.SESSION_COOKIE_SECURE and ProductionConfig.REMEMBER_COOKIE_SECURE
        assert ProductionConfig.SESSION_COOKIE_HTTPONLY


# ======================================================================= query counts

def _count_queries(app, client, url):
    from sqlalchemy import event
    statements = []
    with app.app_context():
        engine = db.engine
    listener = lambda *args: statements.append(1)  # noqa: E731
    event.listen(engine, 'before_cursor_execute', listener)
    try:
        assert client.get(url).status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', listener)
    return len(statements)


def test_notification_and_response_lists_do_not_grow_per_row(app, client, world):
    _login(client, 'admin')
    hazard = world['hazard_a']
    client.post(f'/api/hazards/{hazard}/investigations', json={'note': 'first'})
    baseline = (_count_queries(app, client, '/api/notifications'),
                _count_queries(app, client, f'/api/hazards/{hazard}/investigations'))
    with app.app_context():
        for i in range(8):  # more hazards -> more notifications for the admin
            create_hazard_event('landslide', 'low', 'authority', district_id=world['b'], latitude=26.0 + i, longitude=84)
    for i in range(8):
        client.post(f'/api/hazards/{hazard}/investigations', json={'note': f'note {i}'})
    after = (_count_queries(app, client, '/api/notifications'),
             _count_queries(app, client, f'/api/hazards/{hazard}/investigations'))
    assert after[0] <= baseline[0] and after[1] <= baseline[1], (baseline, after)


# ======================================================================= migrations

def test_fresh_install_is_migration_tracked(tmp_path):
    """init_db.py (create_all) must stamp the head so later `flask db upgrade` works, and the models
    must match the migrations (`flask db check`)."""
    env = {**os.environ, 'DATABASE_URL': f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}", 'FLASK_APP': 'run.py',
           'VISION_ENABLED': 'false', 'PYTHONIOENCODING': 'utf-8'}

    def run(*args):
        return subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)

    assert run('init_db.py').returncode == 0
    current = run('-m', 'flask', 'db', 'current')
    assert 'c3d7f1a9b6e2 (head)' in current.stdout + current.stderr
    for step in (('upgrade',), ('check',), ('downgrade',), ('upgrade',), ('check',)):
        result = run('-m', 'flask', 'db', *step)
        assert result.returncode == 0, (step, result.stderr[-800:])
