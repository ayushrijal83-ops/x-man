"""M07: Disaster Monitoring Dashboard — role scope, aggregation, IoT freshness, reports/AI
visibility, notifications, map data, malformed input, no leaks, read-only, query count."""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Authority, CitizenReport, District, Incident, IoTDevice, Notification, User
from app.models.iot_device import SensorReading
from app.services import dashboard_service
from app.services.hazard_event_service import add_affected_district, create_hazard_event

SECRET_FIELDS = ('source_reference', 'api_key', 'api_key_hash', 'image_filename', 'email', 'raw_payload',
                 'password', 'reporter_id')  # report descriptions are checked by their text


@pytest.fixture
def world(app):
    with app.app_context():
        a, b, c = (District(name=f'District {x}', province='P') for x in 'ABC')
        db.session.add_all([a, b, c])
        db.session.commit()
        auth_a = Authority(name='Auth A', category='water', district_id=a.id)
        auth_b = Authority(name='Auth B', category='water', district_id=b.id)
        db.session.add_all([auth_a, auth_b])
        db.session.commit()
        users = {}
        for name, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None), ('citizen_b', 'citizen', b.id, None),
            ('citizen_none', 'citizen', None, None), ('auth_a', 'authority', a.id, auth_a.id),
            ('auth_b', 'authority', b.id, auth_b.id), ('auth_unlinked', 'authority', a.id, None),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district_id,
                        authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        db.session.commit()

        flood = create_hazard_event('flood', 'high', 'iot', district_id=a.id, latitude=27.2, longitude=85.9,
                                    title='River rising', source_reference='device_1')
        road = create_hazard_event('road_damage', 'medium', 'citizen_report', district_id=b.id,
                                   source_reference='report_9')
        add_affected_district(road, a.id)  # M04: B's road damage also affects A
        quake = create_hazard_event('earthquake', 'critical', 'authority', district_id=c.id)
        old = create_hazard_event('landslide', 'low', 'authority', district_id=a.id)
        old.status = 'resolved'  # history row: not active, must not appear
        db.session.commit()

        now = datetime.utcnow()
        flood_node = IoTDevice(device_id='ESP32-FLOOD-01', name='Flood Node 01', district_id=a.id,
                               authority_id=auth_a.id, latitude=27.21, longitude=85.91, enabled=True,
                               api_key_hash=IoTDevice.hash_api_key('secret-a'), last_seen=now - timedelta(seconds=8))
        seismic = IoTDevice(device_id='ESP32-SEISMIC-01', name='Seismic Node 01', district_id=a.id,
                            authority_id=auth_a.id, enabled=True, api_key_hash=IoTDevice.hash_api_key('secret-s'),
                            last_seen=now - timedelta(minutes=20))
        node_b = IoTDevice(device_id='ESP32-B-01', name='B Node', district_id=b.id, authority_id=auth_b.id,
                           enabled=False, api_key_hash=IoTDevice.hash_api_key('secret-b'))
        db.session.add_all([flood_node, seismic, node_b])
        db.session.commit()
        for device, sensor, value, unit, minutes in [
            (flood_node, 'water_level', 1.10, 'm', 5), (flood_node, 'water_level', 1.25, 'm', 1),
            (flood_node, 'temperature', 27.4, '°C', 1), (flood_node, 'humidity', 81, '%', 1),
            (seismic, 'vibration', 42, 'mg', 20), (seismic, 'tilt', 0.8, '°', 20),
        ]:
            t = now - timedelta(minutes=minutes)
            db.session.add(SensorReading(device_id=device.id, sensor_type=sensor, value=value, unit=unit,
                                         recorded_at=t, received_at=t, raw_payload='{"secret": "x"}'))
        report = CitizenReport(reporter_id=users['citizen_a'].id, district_id=a.id, hazard_type='road_damage',
                               description='private note', location='near the bridge', incident_id=road.id,
                               image_filename='0123456789abcdef0123456789abcdef.jpg', status='submitted',
                               ai_status='completed', ai_label='landslide', ai_confidence=0.84,
                               ai_model='google/siglip-base-patch16-224', ai_model_version='7fd15f0689c7',
                               ai_analyzed_at=now)
        report_b = CitizenReport(reporter_id=users['citizen_b'].id, district_id=b.id, hazard_type='landslide',
                                 image_filename='fedcba9876543210fedcba9876543210.jpg', status='submitted')
        db.session.add_all([report, report_b])
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'c': c.id, 'u': {k: v.id for k, v in users.items()},
                'flood': flood.id, 'road': road.id, 'quake': quake.id, 'old': old.id,
                'devices': {'flood': flood_node.id, 'seismic': seismic.id, 'b': node_b.id},
                'report': report.id, 'report_b': report_b.id}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _dashboard(client, username, query=''):
    _login(client, username)
    response = client.get('/api/dashboard' + query)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _ids(items):
    return sorted(i['id'] for i in items)


class TestAuthAndInput:
    def test_requires_login(self, client, world):
        assert client.get('/api/dashboard').status_code == 401
        assert client.get('/monitoring').status_code == 302

    @pytest.mark.parametrize('value', ['abc', '-1', '0', '1.5', '1;DROP', '%00', '١', '99999999999999999999x'])
    def test_malformed_district_id(self, client, world, value):
        _login(client, 'admin')
        assert client.get(f'/api/dashboard?district_id={value}').status_code == 400

    def test_unknown_district_404(self, client, world):
        _login(client, 'admin')
        assert client.get('/api/dashboard?district_id=99999').status_code == 404

    def test_non_admin_cannot_pick_another_district(self, client, world):
        _login(client, 'citizen_a')
        assert client.get(f"/api/dashboard?district_id={world['b']}").status_code == 403
        assert client.get(f"/api/dashboard?district_id={world['a']}").status_code == 200
        _login(client, 'auth_b')
        assert client.get(f"/api/dashboard?district_id={world['a']}").status_code == 403

    def test_unknown_params_ignored_and_no_cache(self, client, world):
        _login(client, 'citizen_a')
        response = client.get('/api/dashboard?role=admin&limit=99999&user_id=1')
        assert response.status_code == 200 and response.get_json()['role'] == 'citizen'
        assert response.headers['Cache-Control'] == 'private, no-store'


class TestCitizen:
    def test_scope_and_summary(self, client, world):
        data = _dashboard(client, 'citizen_a')
        assert data['scope'] == {'district': {'id': world['a'], 'name': 'District A'}, 'nationwide': False}
        assert _ids(data['hazards']) == sorted([world['flood'], world['road']])  # incl. M04 extra district
        assert data['summary'] == {'total': 2,
                                   'by_type': {'flood': 1, 'earthquake': 0, 'landslide': 0, 'road_damage': 1},
                                   'by_severity': {'low': 0, 'medium': 1, 'high': 1, 'critical': 0}}

    def test_affected_districts_visible(self, client, world):
        road = next(h for h in _dashboard(client, 'citizen_a')['hazards'] if h['id'] == world['road'])
        assert [d['name'] for d in road['affected_districts']] == ['District B', 'District A']

    def test_no_operational_or_private_data(self, client, world):
        _login(client, 'citizen_a')
        body = client.get('/api/dashboard').get_data(as_text=True)
        data = json.loads(body)
        for key in ('devices', 'reports', 'statistics', 'freshness_rule'):
            assert key not in data
        for secret in SECRET_FIELDS + ('ai_analysis', 'private note', 'ESP32-'):
            assert secret not in body

    def test_other_district_not_on_map(self, client, world):
        data = _dashboard(client, 'citizen_b')
        assert _ids(data['hazards']) == [world['road']]
        assert all(h['latitude'] is None for h in data['hazards'])  # A's flood coordinates not sent

    def test_no_home_district_sees_public_nationwide(self, client, world):
        data = _dashboard(client, 'citizen_none')
        assert data['scope']['nationwide'] is True
        assert _ids(data['hazards']) == sorted([world['flood'], world['road'], world['quake']])

    def test_notifications_are_own_only(self, app, client, world):
        data = _dashboard(client, 'citizen_a')
        with app.app_context():
            own = {n.id for n in Notification.query.filter_by(user_id=world['u']['citizen_a'])}
            assert own and {n['id'] for n in data['notifications']} <= own
            assert data['unread_notifications'] == len(own)
        first = data['notifications'][0]
        assert set(first) >= {'severity', 'title', 'message', 'is_read', 'created_at', 'hazard'}
        assert first['hazard']['affected_districts']


class TestAuthority:
    def test_operational_scope(self, client, world):
        data = _dashboard(client, 'auth_a')
        assert _ids(data['hazards']) == sorted([world['flood'], world['road']])
        assert _ids(data['devices']) == sorted([world['devices']['flood'], world['devices']['seismic']])
        assert _ids(data['reports']) == [world['report']]
        assert 'statistics' not in data

    def test_iot_readings_latest_per_sensor(self, client, world):
        devices = {d['name']: d for d in _dashboard(client, 'auth_a')['devices']}
        flood = {r['sensor_type']: (r['value'], r['unit']) for r in devices['Flood Node 01']['readings']}
        assert flood == {'water_level': (1.25, 'm'), 'temperature': (27.4, '°C'), 'humidity': (81, '%')}
        seismic = {r['sensor_type']: (r['value'], r['unit']) for r in devices['Seismic Node 01']['readings']}
        assert seismic == {'vibration': (42, 'mg'), 'tilt': (0.8, '°')}

    def test_device_freshness_labels(self, client, world):
        data = _dashboard(client, 'auth_a')
        devices = {d['name']: d for d in data['devices']}
        assert devices['Flood Node 01']['freshness'] == 'online'
        assert 8 <= devices['Flood Node 01']['seconds_since_seen'] < 60
        assert devices['Seismic Node 01']['freshness'] == 'stale'
        assert devices['Seismic Node 01']['status'] == 'active' and devices['Seismic Node 01']['enabled'] is True
        assert data['freshness_rule'] == {'online_seconds': 300, 'stale_seconds': 3600}

    def test_reports_with_ai_but_no_private_fields(self, client, world):
        _login(client, 'auth_a')
        body = client.get('/api/dashboard').get_data(as_text=True)
        report = json.loads(body)['reports'][0]
        assert report['location'] == 'near the bridge' and report['incident_id'] == world['road']
        assert report['incident_status'] == 'detected' and report['status'] == 'submitted'
        assert report['ai_analysis']['label'] == 'landslide' and report['ai_analysis']['confidence'] == 0.84
        for secret in SECRET_FIELDS + ('private note', 'secret-a', '0123456789abcdef'):
            assert secret not in body

    def test_cross_district_isolation(self, client, world):
        data = _dashboard(client, 'auth_b')
        assert _ids(data['devices']) == [world['devices']['b']]
        assert _ids(data['reports']) == [world['report_b']]
        assert _ids(data['hazards']) == [world['road']]
        assert data['devices'][0]['freshness'] == 'never' and data['devices'][0]['enabled'] is False

    def test_unlinked_authority_sees_nothing_operational(self, client, world):
        data = _dashboard(client, 'auth_unlinked')
        assert data['scope'] == {'district': None, 'nationwide': False}
        assert data['hazards'] == [] and data['devices'] == [] and data['summary']['total'] == 0


class TestAdmin:
    def test_system_wide(self, client, world):
        data = _dashboard(client, 'admin')
        assert data['scope']['nationwide'] is True
        assert _ids(data['hazards']) == sorted([world['flood'], world['road'], world['quake']])
        assert len(data['devices']) == 3 and len(data['reports']) == 2
        stats = data['statistics']
        assert stats['events']['total'] == 4 and stats['events']['by_status']['resolved'] == 1
        assert stats['reports_by_status']['submitted'] == 2
        assert stats['reports_by_ai_status'] == {'not_analyzed': 1, 'completed': 1, 'failed': 0}
        assert stats['devices_total'] == 3 and stats['notifications_last_24h'] > 0
        assert data['summary']['by_severity']['critical'] == 1

    def test_district_filter(self, client, world):
        data = _dashboard(client, 'admin', f"?district_id={world['b']}")
        assert _ids(data['hazards']) == [world['road']]
        assert _ids(data['devices']) == [world['devices']['b']]
        assert _ids(data['reports']) == [world['report_b']]

    def test_no_secrets(self, client, world):
        _login(client, 'admin')
        body = client.get('/api/dashboard').get_data(as_text=True)
        for secret in SECRET_FIELDS + ('secret-a', 'secret-b', 'private note'):
            assert secret not in body


class TestReadOnly:
    def test_dashboard_changes_nothing(self, app, client, world):
        def snapshot():
            with app.app_context():
                return ([(d.status, d.enabled, d.last_seen) for d in IoTDevice.query.order_by(IoTDevice.id)],
                        [(i.status, i.severity, i.updated_at) for i in Incident.query.order_by(Incident.id)],
                        Notification.query.count(), SensorReading.query.count(),
                        [(r.status, r.ai_status) for r in CitizenReport.query.order_by(CitizenReport.id)])
        before = snapshot()
        for user in ('citizen_a', 'auth_a', 'admin'):
            _dashboard(client, user)
            client.get('/monitoring')
        assert snapshot() == before

    @pytest.mark.parametrize('seconds, label', [(0, 'online'), (300, 'online'), (301, 'stale'),
                                                (3600, 'stale'), (3601, 'offline')])
    def test_freshness_rule(self, seconds, label):
        now = datetime(2026, 10, 1, 12, 0, 0)
        assert dashboard_service.freshness(now - timedelta(seconds=seconds), now) == (label, seconds)
        assert dashboard_service.freshness(None, now) == ('never', None)

    def test_query_count_does_not_grow_with_data(self, app, client, world):
        _login(client, 'admin')

        def count_queries():
            statements = []
            listener = lambda *args: statements.append(1)  # noqa: E731
            with app.app_context():
                engine = db.engine
            event.listen(engine, 'before_cursor_execute', listener)
            try:
                assert client.get('/api/dashboard').status_code == 200
            finally:
                event.remove(engine, 'before_cursor_execute', listener)
            return len(statements)

        baseline = count_queries()
        with app.app_context():
            for i in range(10):
                h = create_hazard_event('landslide', 'medium', 'authority', district_id=world['c'],
                                        latitude=28.0 + i, longitude=84.0)
                add_affected_district(h, world['b'])
                device = IoTDevice(device_id=f'X-{i}', name=f'X {i}', district_id=world['c'], enabled=True,
                                   api_key_hash='x', last_seen=datetime.utcnow())
                db.session.add(device)
                db.session.flush()
                db.session.add(SensorReading(device_id=device.id, sensor_type='tilt', value=1, unit='°'))
            db.session.commit()
        assert count_queries() <= baseline  # 10 more hazards/devices/readings, no more queries


class TestPage:
    def test_citizen_page_has_no_operational_sections(self, client, world):
        _login(client, 'citizen_a')
        client.get('/language/set/en')
        body = client.get('/monitoring').get_data(as_text=True)
        assert 'Disaster Monitoring' in body and 'id="mon-map"' in body and '/api/dashboard' in body
        assert 'id="mon-devices"' not in body and 'id="mon-reports"' not in body
        assert 'id="mon-district"' not in body

    def test_manager_and_admin_sections(self, client, world):
        _login(client, 'auth_a')
        client.get('/language/set/en')
        body = client.get('/monitoring').get_data(as_text=True)
        assert 'id="mon-devices"' in body and 'id="mon-reports"' in body and 'id="mon-district"' not in body
        assert 'not an earthquake detection' in body
        _login(client, 'admin')
        assert 'id="mon-district"' in client.get('/monitoring').get_data(as_text=True)

    def test_leaflet_pinned_with_sri_and_polling_documented(self, client, world):
        _login(client, 'citizen_a')
        body = client.get('/monitoring').get_data(as_text=True)
        assert 'leaflet@1.9.4/dist/leaflet.js' in body
        assert 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=' in body
        # H03.10: 10 s through the shared visibility-aware scheduler (live.js), was 30 s
        assert 'visibilitychange' in body and 'POLL_MS = 10 * 1000' in body and "XmanLive.every('dashboard'" in body
        assert 'real-time' not in body.lower()

    def test_nepali(self, client, world):
        _login(client, 'citizen_a')
        client.get('/language/set/ne')
        assert 'विपद् अनुगमन' in client.get('/monitoring').get_data(as_text=True)

    def test_sidebar_link(self, client, world):
        _login(client, 'citizen_a')
        assert 'href="/monitoring"' in client.get('/notifications').get_data(as_text=True)
