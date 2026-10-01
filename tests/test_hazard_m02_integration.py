"""M02 end-to-end checks: IoT telemetry -> hazard event, API security, dedup geometry, legacy pages."""
from app.extensions import db
from app.models import Authority, District, Incident, IoTDevice, River, User
from app.services.hazard_event_service import add_evidence, find_active_related_event


def _setup(app):
    """District A (with river + device + authority) and district B. Returns ids."""
    with app.app_context():
        a = District(name='District A', province='P1')
        b = District(name='District B', province='P1')
        db.session.add_all([a, b])
        db.session.commit()
        river = River(name='Koshi', district_id=a.id, current_level=1.0, danger_level=4.0, status='normal')
        db.session.add(river)
        db.session.commit()
        device = IoTDevice(device_id='ESP32-M02', name='Gauge', district_id=a.id, river_id=river.id,
                           latitude=26.8, longitude=87.2, enabled=True)
        device.api_key_hash = IoTDevice.hash_api_key('k')
        auth_a = Authority(name='Auth A', category='water', district_id=a.id)
        auth_b = Authority(name='Auth B', category='water', district_id=b.id)
        db.session.add_all([device, auth_a, auth_b])
        db.session.commit()
        for username, role, district_id, authority_id in [
            ('citizen', 'citizen', a.id, None),
            ('auth_a', 'authority', a.id, auth_a.id),
            ('auth_b', 'authority', b.id, auth_b.id),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=username, email=f'{username}@t.np', role=role,
                        district_id=district_id, authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'river': river.id}


def _telemetry(client, level):
    return client.post('/api/iot/telemetry', headers={'Authorization': 'Bearer ESP32-M02:k'},
                       json={'readings': [{'sensor_type': 'water_level', 'value': level, 'unit': 'm'}]})


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username == 'citizen' else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _flood_events(app, river_id):
    with app.app_context():
        return Incident.query.filter_by(river_id=river_id, event_type='flood').all()


class TestIoTToHazardEvent:
    def test_normal_reading_creates_no_event(self, app, client):
        ids = _setup(app)
        assert _telemetry(client, 2.0).status_code == 201  # 50%
        assert _flood_events(app, ids['river']) == []

    def test_rising_creates_event_and_repeats_update_it(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)  # 85% -> rising
        _telemetry(client, 3.5)
        _telemetry(client, 4.2)  # flooding

        events = _flood_events(app, ids['river'])
        assert len(events) == 1
        event = events[0]
        assert event.source == 'iot'
        assert event.status == 'detected'  # sensors never confirm on their own
        assert event.severity == 'high'  # escalated by the flooding reading
        assert event.report_count == 3
        assert event.confidence is None  # deterministic threshold, no fake confidence
        assert event.district_id == ids['a']
        assert (event.latitude, event.longitude) == (26.8, 87.2)

    def test_severity_is_not_lowered_by_later_rising_reading(self, app, client):
        ids = _setup(app)
        _telemetry(client, 4.5)  # flooding -> high
        _telemetry(client, 3.4)  # rising
        assert _flood_events(app, ids['river'])[0].severity == 'high'

    def test_resolved_event_is_not_reused(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)
        with app.app_context():
            event = Incident.query.filter_by(river_id=ids['river']).one()
            event.status = 'resolved'
            db.session.commit()
        _telemetry(client, 3.4)
        assert len(_flood_events(app, ids['river'])) == 2


class TestHazardApiSecurity:
    def test_unauthenticated_write_rejected(self, app, client):
        _setup(app)
        assert client.post('/api/hazards', json={'event_type': 'flood'}).status_code == 401

    def test_citizen_cannot_change_status(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)
        event_id = _flood_events(app, ids['river'])[0].id
        _login(client, 'citizen')
        assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'investigating'}).status_code == 403
        assert client.patch(f'/api/hazards/{event_id}', json={'status': 'investigating'}).status_code == 403
        assert client.post(f'/api/hazards/{event_id}/reject', json={}).status_code == 403

    def test_citizen_reports_merge_into_active_event(self, app, client):
        ids = _setup(app)
        _login(client, 'citizen')
        body = {'event_type': 'landslide', 'latitude': 27.70, 'longitude': 85.30}
        first = client.post('/api/hazards', json=body)
        second = client.post('/api/hazards', json={**body, 'latitude': 27.71, 'severity': 'critical'})
        assert first.status_code == 201
        assert second.status_code == 200
        event = second.get_json()['event']
        assert event['id'] == first.get_json()['event']['id']
        assert event['report_count'] == 2
        assert event['severity'] == 'medium'  # M05.1: citizen severity is server-controlled
        assert event['district_id'] == ids['a']  # defaults to the citizen's district

    def test_authority_isolated_to_own_district(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)
        event_id = _flood_events(app, ids['river'])[0].id

        _login(client, 'auth_b')
        assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'investigating'}).status_code == 403
        assert client.post('/api/hazards', json={'event_type': 'flood', 'district_id': ids['a']}).status_code == 403

        _login(client, 'auth_a')
        response = client.patch(f'/api/hazards/{event_id}/status', json={'status': 'investigating'})
        assert response.status_code == 200
        assert response.get_json()['event']['source_reference'].startswith('device_')

    def test_admin_can_manage_any_district(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)
        event_id = _flood_events(app, ids['river'])[0].id
        _login(client, 'admin')
        assert client.post(f'/api/hazards/{event_id}/reject', json={'reason': 'gauge fault'}).status_code == 200

    def test_authority_cannot_spoof_source(self, app, client):
        _setup(app)
        _login(client, 'auth_a')
        response = client.post('/api/hazards', json={'event_type': 'road_damage', 'source': 'iot', 'confidence': 0.99})
        assert response.status_code == 201
        event = response.get_json()['event']
        assert event['source'] == 'authority'
        assert event['confidence'] is None

    def test_malformed_and_invalid_payloads(self, app, client):
        _setup(app)
        _login(client, 'auth_a')
        bad = [
            client.post('/api/hazards', data='{not json', content_type='application/json'),
            client.post('/api/hazards', json=['flood']),
            client.post('/api/hazards', json={'event_type': 'flood', 'latitude': 'x', 'longitude': 85}),
            client.post('/api/hazards', json={'event_type': 'flood', 'latitude': 27.7}),
            client.post('/api/hazards', json={'event_type': 'flood', 'district_id': '1'}),
            client.post('/api/hazards', json={'event_type': 'flood', 'title': 'x' * 201}),
            client.post('/api/hazards', json={'event_type': 'volcano'}),
        ]
        assert [r.status_code for r in bad] == [400] * len(bad)
        assert all('error' in r.get_json() for r in bad)


class TestDedupGeometry:
    def test_longitude_radius_scales_with_latitude(self, app):
        with app.app_context():
            db.session.add(Incident(event_type='landslide', severity='high', source='citizen_report',
                                    latitude=27.7, longitude=85.3, status='detected'))
            db.session.commit()
            # at 27.7N one degree of longitude is ~98 km
            assert find_active_related_event('landslide', latitude=27.7, longitude=85.34) is not None  # ~4 km
            assert find_active_related_event('landslide', latitude=27.7, longitude=85.50) is None  # ~20 km
            assert find_active_related_event('flood', latitude=27.7, longitude=85.3) is None  # other type

    def test_add_evidence_never_lowers_severity(self, app):
        with app.app_context():
            incident = Incident(event_type='flood', severity='critical', source='authority', status='detected')
            db.session.add(incident)
            db.session.commit()
            add_evidence(incident, 'low')
            assert incident.severity == 'critical'
            assert incident.report_count == 2


class TestLegacyPagesUseNewLifecycle:
    def test_travel_planner_lists_active_hazard_events(self, app, client):
        ids = _setup(app)
        with app.app_context():
            db.session.add(Incident(event_type='landslide', severity='critical', source='authority',
                                    district_id=ids['a'], status='confirmed'))
            db.session.commit()
        _login(client, 'citizen')
        response = client.post('/travel/planner', data={'from_location': 'District A', 'to_location': 'District B'})
        assert response.status_code == 200
        assert b'CRITICAL: landslide' in response.data

    def test_district_page_renders(self, app, client):
        ids = _setup(app)
        _telemetry(client, 3.4)
        _login(client, 'citizen')
        assert client.get(f'/district/{ids["a"]}').status_code == 200
