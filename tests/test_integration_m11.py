"""M11: full software integration tests.

Each test drives several X-MAN components together through the real HTTP API and then checks
the database rows, not just status codes. Sensor input is SYNTHETIC: these requests stand in for
future ESP32/JSN-SR04T/MPU6050 telemetry. Physical hardware has not been validated.

Pipeline under test:
  telemetry/report -> validation -> risk (M08) -> hazard event (M02) -> affected districts (M04)
  -> notifications (M03/M04) -> dashboard (M07) -> authority response (M09) -> resolution
"""
import io
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func

from app.extensions import db
from app.models import (Authority, CitizenReport, District, Incident, IncidentAffectedDistrict,
                        IncidentInvestigation, IncidentResponseAction, IncidentStatusHistory, IoTDevice,
                        Notification, River, User)
from app.models.iot_device import SensorReading
from app.services import authority_response_service, citizen_report_service, notification_service, vision_service
from test_vision_m06 import GRAY, GREEN, RED, PixelStub, _jpeg  # M06 deterministic vision stub (no model, no network)

DEVICE_KEYS = {'FLOOD-A': 'k-flood-a', 'MOTION-A': 'k-motion-a', 'MOTION-B': 'k-motion-b'}
# M03 recipients for a district-A hazard: everyone whose home district is A (citizens and authority
# users, linked or not), authority users responsible for A, and admins.
RECIPIENTS_A = ('citizen_a', 'citizen_a2', 'auth_a', 'auth_unlinked', 'admin')


# ============================================================================ fixtures / helpers

@pytest.fixture
def world(app, tmp_path):
    app.config['REPORT_UPLOAD_DIR'] = str(tmp_path / 'reports')
    with app.app_context():
        districts = {k: District(name=f'District {k.upper()}', province='P') for k in 'abcd'}
        db.session.add_all(districts.values())
        db.session.commit()
        auth_a = Authority(name='Auth A', category='water', district_id=districts['a'].id)
        auth_b = Authority(name='Auth B', category='roads', district_id=districts['b'].id)
        river = River(name='River A', district_id=districts['a'].id, current_level=1.0, danger_level=4.0,
                      status='normal')
        db.session.add_all([auth_a, auth_b, river])
        db.session.commit()
        users = {}
        for name, role, district, authority in [
            ('citizen_a', 'citizen', 'a', None), ('citizen_a2', 'citizen', 'a', None),
            ('citizen_b', 'citizen', 'b', None), ('citizen_c', 'citizen', 'c', None),
            ('citizen_d', 'citizen', 'd', None), ('auth_a', 'authority', 'a', auth_a),
            ('auth_b', 'authority', 'b', auth_b), ('auth_unlinked', 'authority', 'a', None),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=name, email=f'{name}@t.np', role=role,
                        district_id=districts[district].id if district else None,
                        authority_id=authority.id if authority else None)
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        devices = {}
        for key, district, authority, river_id, lat in [('FLOOD-A', 'a', auth_a, river.id, 27.20),
                                                         ('MOTION-A', 'a', auth_a, None, 27.30),
                                                         ('MOTION-B', 'b', auth_b, None, 26.80)]:
            device = IoTDevice(device_id=key, name=key.title(), district_id=districts[district].id,
                               authority_id=authority.id, river_id=river_id, latitude=lat, longitude=85.9,
                               enabled=True, api_key_hash=IoTDevice.hash_api_key(DEVICE_KEYS[key]))
            db.session.add(device)
            devices[key] = device
        db.session.commit()
        return {'d': {k: v.id for k, v in districts.items()}, 'u': {k: v.id for k, v in users.items()},
                'dev': {k: v.id for k, v in devices.items()}, 'river': river.id}


@pytest.fixture
def vision(app, monkeypatch):
    stub = PixelStub()
    monkeypatch.setattr(vision_service, '_classifier', stub)
    app.config['VISION_ENABLED'] = True
    return stub


def login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def telemetry(client, device, *readings, timestamp=None):
    body = {'readings': list(readings)}
    if timestamp:
        body['timestamp'] = timestamp
    return client.post('/api/iot/telemetry', json=body,
                       headers={'Authorization': f'Bearer {device}:{DEVICE_KEYS[device]}'})


def water(value):
    return {'sensor_type': 'water_level', 'value': value, 'unit': 'm'}


def report(client, world, user, hazard, color, district='a', lat='27.25', description=None):
    login(client, user)
    data = {'hazard_type': hazard, 'district_id': str(world['d'][district]), 'latitude': lat, 'longitude': '85.90',
            'image': (io.BytesIO(_jpeg(color)), 'photo.jpg', 'image/jpeg')}
    if description:
        data['description'] = description
    response = client.post('/api/reports', data=data, content_type='multipart/form-data')
    assert response.status_code == 201, response.get_json()
    return response.get_json()['report']


def alerts(app, ntype=None):
    """{username: sorted notification types} for hazard alerts (not report receipts)."""
    with app.app_context():
        query = db.session.query(User.username, Notification.type).join(User, User.id == Notification.user_id) \
            .filter(Notification.type != 'report_update')
        if ntype:
            query = query.filter(Notification.type == ntype)
        rows = query.all()
    result = {}
    for username, ntype in rows:
        result.setdefault(username, []).append(ntype)
    return {k: sorted(v) for k, v in result.items()}


def incident_row(app, event_id):
    with app.app_context():
        incident = db.session.get(Incident, event_id)
        db.session.expunge(incident)
        return incident


def history(app, event_id):
    with app.app_context():
        return [(h.previous_status, h.new_status, h.changed_by.username if h.changed_by else None)
                for h in IncidentStatusHistory.query.filter_by(incident_id=event_id).order_by(IncidentStatusHistory.id)]


def counts(app, *models):
    with app.app_context():
        return tuple(db.session.query(func.count(m.id)).scalar() for m in models)


# ============================================================================ flood: master end-to-end

def test_iot_flood_pipeline_end_to_end_through_resolution(app, client, world):
    """Telemetry -> auth -> validation -> M08 risk -> M02 event -> M03 alerts -> M07 dashboards ->
    M09 investigate/confirm/respond/resolve -> resolution alert, checking DB state at each step."""
    # 1. normal reading: stored, river updated, no event
    assert telemetry(client, 'FLOOD-A', water(2.0)).status_code == 201
    with app.app_context():
        assert db.session.get(River, world['river']).status == 'normal'
        assert Incident.query.count() == 0 and SensorReading.query.count() == 1

    # 2. rising (85%): one medium flood event + one detected alert per recipient in district A
    assert telemetry(client, 'FLOOD-A', water(3.4)).status_code == 201
    with app.app_context():
        event = Incident.query.one()
        event_id, description = event.id, event.description
        assert (event.event_type, event.severity, event.status, event.source) == ('flood', 'medium', 'detected', 'iot')
        assert (event.district_id, event.river_id, event.affected_district_ids) == \
            (world['d']['a'], world['river'], [world['d']['a']])
        assert db.session.get(River, world['river']).status == 'rising'
    assert alerts(app) == {name: ['hazard_detected'] for name in RECIPIENTS_A}

    # 3. dashboards: citizen sees the public hazard, authority also sees the device's latest reading
    login(client, 'citizen_a')
    dash = client.get('/api/dashboard').get_json()
    assert [h['id'] for h in dash['hazards']] == [event_id] and dash['summary']['by_severity']['medium'] == 1
    assert dash['unread_notifications'] == 1 and 'devices' not in dash
    login(client, 'auth_a')
    dash = client.get('/api/dashboard').get_json()
    flood_node = next(d for d in dash['devices'] if d['device_id'] == 'FLOOD-A')
    assert {r['sensor_type']: r['value'] for r in flood_node['readings']} == {'water_level': 3.4}
    assert flood_node['freshness'] == 'online'

    # 4. flooding (105%): same event escalated to high, one escalation alert per recipient
    assert telemetry(client, 'FLOOD-A', water(4.2)).status_code == 201
    with app.app_context():
        event = db.session.get(Incident, event_id)
        assert (Incident.query.count(), event.severity, event.report_count) == (1, 'high', 2)
    assert alerts(app, ntype='hazard_escalated') == {n: ['hazard_escalated'] for n in RECIPIENTS_A}

    # 5. authority response (M09) with investigation note and a tracked response action
    base = f'/api/hazards/{event_id}'
    assert client.post(f'{base}/status', json={'status': 'investigating', 'note': 'Team dispatched'}).status_code == 200
    assert client.post(f'{base}/investigations', json={'note': 'Water over the bridge marker'}).status_code == 201
    assert client.post(f'{base}/status', json={'status': 'confirmed'}).status_code == 200
    assert client.post(f'{base}/status', json={'status': 'response'}).status_code == 200
    action = client.post(f'{base}/response-actions', json={'action_type': 'close_road',
                                                           'description': 'Close river road'}).get_json()
    action_url = f"{base}/response-actions/{action['response_action']['id']}"
    assert client.patch(action_url, json={'status': 'in_progress'}).status_code == 200
    assert client.patch(action_url, json={'status': 'completed'}).status_code == 200
    assert client.post(f'{base}/status', json={'status': 'resolved'}).status_code == 400  # note required
    assert client.post(f'{base}/status', json={'status': 'resolved',
                                               'note': 'Level back under danger mark'}).status_code == 200

    # 6. database state after the whole flow
    assert history(app, event_id) == [('detected', 'investigating', 'auth_a'), ('investigating', 'confirmed', 'auth_a'),
                                      ('confirmed', 'response', 'auth_a'), ('response', 'resolved', 'auth_a')]
    with app.app_context():
        event = db.session.get(Incident, event_id)
        assert (event.status, event.severity, event.description) == ('resolved', 'high', description)
        assert event.resolved_at is not None
        action_row = db.session.get(IncidentResponseAction, action['response_action']['id'])
        assert (action_row.status, action_row.incident_id, action_row.author.username) == ('completed', event_id, 'auth_a')
        assert action_row.completed_at is not None
        note = IncidentInvestigation.query.one()
        assert (note.incident_id, note.author.username) == (event_id, 'auth_a')
        assert {n.incident_id for n in Notification.query} == {event_id}  # FK integrity of every alert
        assert {r.device.device_id for r in SensorReading.query} == {'FLOOD-A'}
    expected = ['hazard_confirmed', 'hazard_detected', 'hazard_escalated', 'hazard_resolved']
    assert alerts(app) == {n: expected for n in RECIPIENTS_A}

    # 7. notification ownership: unread, mark one, mark all
    login(client, 'citizen_a')
    listed = client.get('/api/notifications').get_json()
    assert listed['unread_count'] == 4 and len(listed['notifications']) == 4
    assert client.post(f"/api/notifications/{listed['notifications'][0]['id']}/read").status_code == 200
    assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 3
    client.post('/api/notifications/read-all')
    assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 0
    with app.app_context():
        assert Notification.query.filter_by(user_id=world['u']['citizen_a2'], is_read=False).count() == 4
    # resolved hazards leave the active dashboard
    assert client.get('/api/dashboard').get_json()['hazards'] == []


def test_repeated_telemetry_does_not_spam_alerts(app, client, world):
    for _ in range(4):
        assert telemetry(client, 'FLOOD-A', water(3.5)).status_code == 201
    for _ in range(3):
        assert telemetry(client, 'FLOOD-A', water(4.5)).status_code == 201
    with app.app_context():
        event = Incident.query.one()
        assert (event.severity, event.report_count) == ('high', 7)
        assert SensorReading.query.count() == 7
    per_user = alerts(app)
    assert per_user['citizen_a'] == ['hazard_detected', 'hazard_escalated']  # one of each, not 4 + 3
    assert set(per_user) == set(RECIPIENTS_A)


def test_invalid_telemetry_does_not_corrupt_existing_state(app, client, world):
    telemetry(client, 'FLOOD-A', water(3.5))
    before = incident_row(app, 1)
    snapshot = (counts(app, Notification), before.severity, before.report_count)
    response = client.post('/api/iot/telemetry', data='{"readings":[{"sensor_type":"water_level","value":NaN,"unit":"m"},'
                                                      '{"sensor_type":"water_level","value":450,"unit":"cm"}]}',
                           content_type='application/json',
                           headers={'Authorization': f"Bearer FLOOD-A:{DEVICE_KEYS['FLOOD-A']}"})
    assert response.status_code == 400
    assert telemetry(client, 'FLOOD-A', water(9.0), timestamp='not-a-time').status_code == 400
    assert client.post('/api/iot/telemetry', json={'readings': [water(9.0)]},
                       headers={'Authorization': 'Bearer FLOOD-A:wrong'}).status_code == 401
    # a mixed batch stores only the valid reading and still flows through the risk engine
    mixed = telemetry(client, 'FLOOD-A', water(3.6), {'sensor_type': 'water_level', 'value': True, 'unit': 'm'})
    assert mixed.status_code == 201 and mixed.get_json()['stored'] == 1
    after = incident_row(app, 1)
    assert (counts(app, Notification), after.severity, after.report_count) == \
        (snapshot[0], snapshot[1], snapshot[2] + 1)
    with app.app_context():
        assert [r.value for r in SensorReading.query.order_by(SensorReading.id)] == [3.5, 3.6]


def test_latest_readings_reach_dashboard_per_sensor_type(app, client, world):
    now = datetime.utcnow()
    telemetry(client, 'FLOOD-A', water(1.2), timestamp=(now - timedelta(minutes=10)).isoformat() + 'Z')
    telemetry(client, 'FLOOD-A', water(1.4), timestamp=(now - timedelta(minutes=1)).isoformat() + 'Z')
    telemetry(client, 'MOTION-A', {'sensor_type': 'vibration', 'value': 35, 'unit': 'mg'},
              {'sensor_type': 'tilt', 'value': 0.6, 'unit': '°'})
    telemetry(client, 'MOTION-A', {'sensor_type': 'vibration', 'value': 41, 'unit': 'mg'})
    login(client, 'auth_a')
    devices = {d['device_id']: {r['sensor_type']: (r['value'], r['unit']) for r in d['readings']}
               for d in client.get('/api/dashboard').get_json()['devices']}
    assert devices['FLOOD-A'] == {'water_level': (1.4, 'm')}
    assert devices['MOTION-A'] == {'vibration': (41, 'mg'), 'tilt': (0.6, '°')}
    assert 'MOTION-B' not in devices  # other authority's device
    latest = client.get('/api/iot/latest').get_json()['readings']
    assert sorted((r['sensor_type'], r['value']) for r in latest) == [('tilt', 0.6), ('vibration', 41.0),
                                                                      ('water_level', 1.4)]


# ============================================================================ seismic (software simulation)

def test_seismic_software_simulation_of_mpu6050_input(app, client, world):
    """Synthetic vibration/tilt telemetry standing in for a future MPU6050 node (not hardware validation)."""
    strong = {'sensor_type': 'vibration', 'value': 800, 'unit': 'mg'}
    for _ in range(5):  # default config: thresholds unset -> uncharacterized -> never an automatic event
        assert telemetry(client, 'MOTION-A', strong).status_code == 201
    with app.app_context():
        assert Incident.query.count() == 0

    app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300  # what a future characterization would set
    with app.app_context():
        SensorReading.query.delete()
        db.session.commit()
    for value in (12, 950, 15):  # one isolated spike inside the window
        telemetry(client, 'MOTION-A', {'sensor_type': 'vibration', 'value': value, 'unit': 'mg'})
    with app.app_context():
        assert Incident.query.count() == 0

    for _ in range(3):  # sustained abnormal motion -> one event
        telemetry(client, 'MOTION-A', strong)
    for _ in range(3):  # more of the same merges, never escalates
        telemetry(client, 'MOTION-A', strong)
    with app.app_context():
        event = Incident.query.one()
        assert (event.event_type, event.severity, event.source, event.status) == ('earthquake', 'medium', 'iot', 'detected')
        assert event.district_id == world['d']['a'] and event.report_count >= 2
        assert event.title == 'Abnormal ground motion signal: Motion-A'
        text = f'{event.title} {event.description}'.lower()
        assert 'not a prediction' in text and 'no magnitude' in text and 'certified' in text
        assert 'richter' not in text and 'predicted' not in text
    assert alerts(app, ntype='hazard_escalated') == {}
    assert 'citizen_b' not in alerts(app)  # district B untouched
    login(client, 'auth_a')
    assessments = client.get(f'/api/hazards/{event.id}/assessment').get_json()['assessments']
    motion = next(a for a in assessments if a['evidence'].get('device') == 'Motion-A')
    assert motion['level'] == 'elevated_motion' and motion['severity'] == 'medium'


# ============================================================================ citizen reports + vision

def test_landslide_reports_flow_through_vision_dedup_and_authority_response(app, client, world, vision):
    first = report(client, world, 'citizen_a', 'landslide', GREEN, description='Mud on the road near school')
    second = report(client, world, 'citizen_a2', 'landslide', GRAY, lat='27.26')  # AI unknown
    duplicate = report(client, world, 'citizen_a', 'landslide', GREEN, lat='27.25')  # same reporter again
    assert first['incident_id'] == second['incident_id'] == duplicate['incident_id']
    event_id = first['incident_id']
    with app.app_context():
        event = db.session.get(Incident, event_id)
        assert (Incident.query.count(), event.report_count, event.severity, event.status) == (1, 3, 'medium', 'detected')
        labels = {r.id: (r.ai_status, r.ai_label) for r in CitizenReport.query}
    assert labels[first['id']] == ('completed', 'landslide') and labels[second['id']] == ('completed', 'unknown')
    # reporters get receipts, not alerts about their own report; neighbours get one detected alert
    assert alerts(app)['citizen_a2'] == ['hazard_detected']

    login(client, 'auth_a')
    reviewed = client.get(f"/api/reports/{first['id']}").get_json()['report']
    assert reviewed['ai_analysis']['label'] == 'landslide' and reviewed['description'] == 'Mud on the road near school'
    [grade] = client.get(f'/api/hazards/{event_id}/assessment').get_json()['assessments']
    assert grade['level'] == 'corroborated'
    assert (grade['evidence']['distinct_reporters'], grade['evidence']['reports']) == (2, 3)  # duplicate counted once
    assert client.post(f"/api/reports/{second['id']}/review", json={'status': 'rejected'}).status_code == 200
    [grade] = client.get(f'/api/hazards/{event_id}/assessment').get_json()['assessments']
    assert grade['level'] == 'supported' and grade['evidence']['rejected_reports'] == 1  # rejected evidence ignored
    assert incident_row(app, event_id).severity == 'medium'  # evidence never escalates

    for status in ('investigating', 'confirmed', 'response'):
        assert client.post(f'/api/hazards/{event_id}/status', json={'status': status}).status_code == 200
    assert client.post(f'/api/hazards/{event_id}/status',
                       json={'status': 'resolved', 'note': 'Debris cleared'}).status_code == 200
    with app.app_context():
        assert db.session.get(CitizenReport, first['id']).ai_label == 'landslide'  # AI evidence untouched by M09
    assert incident_row(app, event_id).status == 'resolved'
    assert alerts(app)['citizen_a2'] == ['hazard_confirmed', 'hazard_detected', 'hazard_resolved']


def test_road_damage_ai_disagreement_stays_evidence(app, client, world, vision):
    submitted = report(client, world, 'citizen_a', 'road_damage', GREEN)  # AI says landslide
    event_id = submitted['incident_id']
    with app.app_context():
        row = db.session.get(CitizenReport, submitted['id'])
        event = db.session.get(Incident, event_id)
        assert (row.hazard_type, row.ai_label, row.status) == ('road_damage', 'landslide', 'submitted')
        assert (event.event_type, event.severity, event.status, event.affected_district_ids) == \
            ('road_damage', 'medium', 'detected', [world['d']['a']])
    assert set(t for types in alerts(app).values() for t in types) == {'hazard_detected'}
    login(client, 'auth_a')
    [grade] = client.get(f'/api/hazards/{event_id}/assessment').get_json()['assessments']
    assert grade['level'] == 'single_report' and grade['evidence']['ai_conflict'] == 1
    client.get('/language/set/en')
    page = client.get('/reports/review').get_data(as_text=True)
    assert 'differs from citizen' in page
    # authority decides: confirm, respond with an action, resolve
    base = f'/api/hazards/{event_id}'
    for status in ('investigating', 'confirmed', 'response'):
        assert client.post(f'{base}/status', json={'status': status}).status_code == 200
    action = client.post(f'{base}/response-actions', json={'action_type': 'place_warning', 'status': 'completed',
                                                           'description': 'Warning signs placed'}).get_json()
    assert action['response_action']['completed_at'] is not None
    assert client.post(f'{base}/resolve', json={'resolution_notes': 'Road patched'}).status_code == 200
    assert history(app, event_id)[-1] == ('response', 'resolved', 'auth_a')
    assert client.post(f'{base}/status', json={'status': 'investigating'}).status_code == 400  # terminal


def test_vision_failure_and_report_write_failure_leave_consistent_state(app, client, world, monkeypatch, tmp_path):
    app.config['VISION_ENABLED'] = True
    monkeypatch.setattr(vision_service, '_classifier', PixelStub(fail=True))
    kept = report(client, world, 'citizen_a', 'landslide', RED)
    with app.app_context():
        row = db.session.get(CitizenReport, kept['id'])
        assert (row.ai_status, row.status, row.incident_id is not None) == ('failed', 'submitted', True)
    login(client, 'auth_a')
    image = client.get(f"/api/reports/{kept['id']}/image")
    assert image.status_code == 200 and image.mimetype == 'image/jpeg'
    image.close()
    monkeypatch.setattr(vision_service, '_classifier', PixelStub())  # model back: reviewer re-runs analysis
    rerun = client.post(f"/api/reports/{kept['id']}/analyze").get_json()['report']['ai_analysis']
    assert (rerun['status'], rerun['label']) == ('completed', 'road_damage')

    # database failure while linking the report to a hazard: nothing half-written, no orphan file
    before = counts(app, CitizenReport, Incident, Notification)
    files_before = sorted(p.name for p in (tmp_path / 'reports').iterdir())

    def failing_report_hazard(*args, **kwargs):
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(citizen_report_service, 'report_hazard', failing_report_hazard)
    app.config['PROPAGATE_EXCEPTIONS'] = False
    login(client, 'citizen_a2')
    response = client.post('/api/reports', content_type='multipart/form-data', data={
        'hazard_type': 'landslide', 'district_id': str(world['d']['a']),
        'image': (io.BytesIO(_jpeg(RED)), 'p.jpg', 'image/jpeg')})
    assert response.status_code == 500 and 'simulated' not in response.get_data(as_text=True)
    assert counts(app, CitizenReport, Incident, Notification) == before
    assert sorted(p.name for p in (tmp_path / 'reports').iterdir()) == files_before


# ============================================================================ affected districts (M04)

def test_affected_districts_target_alerts_and_keep_m09_primary_scope(app, client, world):
    telemetry(client, 'FLOOD-A', water(3.4))
    event_id = incident_row(app, 1).id
    login(client, 'admin')
    for district in ('b', 'c'):
        assert client.post(f'/api/hazards/{event_id}/affected-districts',
                           json={'district_id': world['d'][district]}).status_code == 201
    assert client.post(f'/api/hazards/{event_id}/affected-districts',
                       json={'district_id': world['d']['b']}).status_code == 409
    per_user = alerts(app)
    assert per_user['citizen_b'] == per_user['citizen_c'] == ['hazard_detected']
    assert per_user['auth_b'] == ['hazard_detected'] and 'citizen_d' not in per_user  # outside: nothing
    with app.app_context():
        rows = IncidentAffectedDistrict.query.filter_by(incident_id=event_id).all()
        assert sorted(r.district_id for r in rows) == [world['d']['b'], world['d']['c']]
        assert db.session.get(Incident, event_id).district_id == world['d']['a']

    assert client.delete(f"/api/hazards/{event_id}/affected-districts/{world['d']['c']}").status_code == 200
    assert alerts(app)['citizen_c'] == ['hazard_detected']  # history kept
    telemetry(client, 'FLOOD-A', water(4.4))  # escalation reaches current areas only
    per_user = alerts(app, ntype='hazard_escalated')
    assert {'citizen_a', 'citizen_b', 'auth_b', 'admin'} <= set(per_user) and 'citizen_c' not in per_user

    login(client, 'auth_b')  # sees it (affected district) but can't manage it (M02/M09 primary rule)
    assert event_id in [h['id'] for h in client.get('/api/dashboard').get_json()['hazards']]
    assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'investigating'}).status_code == 403
    login(client, 'auth_a')
    assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'investigating'}).status_code == 200
    assert client.post(f'/api/hazards/{event_id}/status', json={'status': 'confirmed'}).status_code == 200
    login(client, 'admin')
    client.post(f'/api/hazards/{event_id}/affected-districts', json={'district_id': world['d']['d']})
    assert alerts(app)['citizen_d'] == ['hazard_confirmed', 'hazard_detected']  # brought up to date once
    assert alerts(app)['citizen_b'].count('hazard_detected') == 1


# ============================================================================ multi-signal scoping (M08)

def test_multi_signal_evidence_stays_within_event_scope(app, client, world, vision):
    app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300
    for level in (3.3, 3.4, 3.5):
        telemetry(client, 'FLOOD-A', water(level))
    b_report = report(client, world, 'citizen_b', 'landslide', GREEN, district='b', lat='26.80')
    for _ in range(3):
        telemetry(client, 'MOTION-B', {'sensor_type': 'vibration', 'value': 500, 'unit': 'mg'})
    with app.app_context():
        events = {i.event_type: i for i in Incident.query}
        assert set(events) == {'flood', 'landslide', 'earthquake'}
        assert events['flood'].district_id == world['d']['a']
        assert events['landslide'].district_id == events['earthquake'].district_id == world['d']['b']
        ids = {k: v.id for k, v in events.items()}
    login(client, 'admin')
    [flood] = client.get(f"/api/hazards/{ids['flood']}/assessment").get_json()['assessments']
    assert flood['evidence']['valid_readings'] == 3 and flood['evidence']['corroborating_readings'] == 3
    [landslide] = client.get(f"/api/hazards/{ids['landslide']}/assessment").get_json()['assessments']
    assert landslide['sources'] == ['citizen_report', 'vision_ai'] and landslide['district_id'] == world['d']['b']
    quake = client.get(f"/api/hazards/{ids['earthquake']}/assessment").get_json()['assessments']
    assert [a['evidence']['device'] for a in quake] == ['Motion-B']  # only district B devices
    # district A citizens only hear about district A
    assert alerts(app)['citizen_a'] == ['hazard_detected']
    with app.app_context():
        assert {n.incident_id for n in Notification.query.filter_by(user_id=world['u']['citizen_a'])} == {ids['flood']}
    login(client, 'citizen_a')
    assert [h['event_type'] for h in client.get('/api/dashboard').get_json()['hazards']] == ['flood']
    login(client, 'auth_a')
    assert client.get(f"/api/hazards/{ids['landslide']}/assessment").status_code == 403
    assert client.get(f"/api/reports/{b_report['id']}").status_code == 404


# ============================================================================ concurrency / failure injection

def test_concurrent_confirmations_one_wins(app, client, world, monkeypatch):
    """Two authorities confirm the same hazard at once: the second request (separate client, separate
    app context and DB session) is fired at the exact moment the first has validated, so both pass
    validation; the M09 compare-and-set lets exactly one commit."""
    telemetry(client, 'FLOOD-A', water(3.4))
    login(client, 'auth_a')
    client.post('/api/hazards/1/status', json={'status': 'investigating'})
    competitor = app.test_client()
    login(competitor, 'admin')
    real_validate = authority_response_service.validate_status_request
    results = {}

    def validate_then_race(incident, new_status, note):
        clean = real_validate(incident, new_status, note)
        if 'second' not in results:
            results['second'] = None  # set first: the competing request runs this same function
            with app.app_context():  # its own app context = its own DB session, like a real parallel request
                results['second'] = competitor.post('/api/hazards/1/status', json={'status': 'confirmed'}).status_code
        return clean
    monkeypatch.setattr(authority_response_service, 'validate_status_request', validate_then_race)
    results['first'] = client.post('/api/hazards/1/status', json={'status': 'confirmed'}).status_code
    assert sorted(results.values()) == [200, 409]
    assert results == {'second': 200, 'first': 409}  # the request that committed first wins
    assert history(app, 1) == [('detected', 'investigating', 'auth_a'), ('investigating', 'confirmed', 'admin')]
    assert incident_row(app, 1).status == 'confirmed'
    assert alerts(app, ntype='hazard_confirmed') == {n: ['hazard_confirmed'] for n in RECIPIENTS_A}


def test_notification_failure_rolls_back_whole_operation(app, client, world, monkeypatch):
    """Documented guarantee: alerts are written in the same transaction as the event/status change,
    so a notification failure aborts that change (the client gets a 500 and can retry)."""
    app.config['PROPAGATE_EXCEPTIONS'] = False

    def failing_notify(*args, **kwargs):
        raise RuntimeError('simulated notification failure')
    monkeypatch.setattr(notification_service, 'notify_hazard', failing_notify)
    response = telemetry(client, 'FLOOD-A', water(3.4))
    assert response.status_code == 500 and response.get_json() == {'error': 'Internal server error'}
    assert counts(app, Incident, Notification, SensorReading) == (0, 0, 0)  # readings in the same transaction
    monkeypatch.undo()

    assert telemetry(client, 'FLOOD-A', water(3.4)).status_code == 201  # retry succeeds
    login(client, 'auth_a')
    client.post('/api/hazards/1/status', json={'status': 'investigating'})
    monkeypatch.setattr(notification_service, 'notify_hazard', failing_notify)
    before = counts(app, Notification, IncidentStatusHistory)
    assert client.post('/api/hazards/1/status', json={'status': 'confirmed'}).status_code == 500
    assert incident_row(app, 1).status == 'investigating'
    assert counts(app, Notification, IncidentStatusHistory) == before


# ============================================================================ security + privacy across the pipeline

def test_cross_component_authorization_on_live_state(app, client, world, vision):
    telemetry(client, 'FLOOD-A', water(3.4))
    submitted = report(client, world, 'citizen_a', 'landslide', GREEN)
    checks = [
        ('citizen_a', 'post', '/api/hazards/1/status', {'status': 'investigating'}, 403),
        ('citizen_a', 'post', '/api/hazards/1/investigations', {'note': 'x'}, 403),
        ('citizen_a', 'get', '/api/iot/devices', None, 403),
        ('citizen_b', 'get', f"/api/reports/{submitted['id']}", None, 404),
        ('auth_b', 'post', '/api/hazards/1/status', {'status': 'investigating'}, 403),
        ('auth_b', 'get', f"/api/reports/{submitted['id']}/image", None, 404),
        ('auth_b', 'patch', f"/api/iot/devices/{world['dev']['FLOOD-A']}", {'enabled': False}, 403),
        ('auth_unlinked', 'get', f"/api/iot/devices?district_id={world['d']['a']}", None, 403),
        ('auth_unlinked', 'post', f"/api/iot/devices/{world['dev']['FLOOD-A']}/rotate-key", None, 403),
        ('auth_unlinked', 'post', '/api/hazards/1/status', {'status': 'investigating'}, 403),
        ('admin', 'get', '/api/hazards/1/status-history', None, 200),
    ]
    for who, method, url, body, expected in checks:
        login(client, who)
        assert getattr(client, method)(url, json=body).status_code == expected, (who, url)
    # one device's key cannot post as another
    response = client.post('/api/iot/telemetry', json={'readings': [water(3.9)]},
                           headers={'Authorization': f"Bearer FLOOD-A:{DEVICE_KEYS['MOTION-A']}"})
    assert response.status_code == 401
    with app.app_context():
        device = db.session.get(IoTDevice, world['dev']['FLOOD-A'])
        assert device.enabled and device.verify_api_key(DEVICE_KEYS['FLOOD-A'])
    assert history(app, 1) == []


def test_private_data_never_leaks_through_integrated_apis(app, client, world, vision):
    telemetry(client, 'FLOOD-A', water(3.4))
    submitted = report(client, world, 'citizen_a', 'landslide', GREEN, description='PRIVATE-REPORT-TEXT')
    login(client, 'auth_a')
    client.post('/api/hazards/1/investigations', json={'note': 'INTERNAL-NOTE'})
    client.post('/api/hazards/1/response-actions', json={'action_type': 'evacuate_area',
                                                         'description': 'INTERNAL-ACTION'})
    for status in ('investigating', 'confirmed', 'response'):
        client.post('/api/hazards/1/status', json={'status': status})
    client.post('/api/hazards/1/status', json={'status': 'resolved', 'note': 'INTERNAL-RESOLUTION'})
    with app.app_context():
        key_hash = db.session.get(IoTDevice, world['dev']['FLOOD-A']).api_key_hash
        source_refs = [i.source_reference for i in Incident.query]
    # (the model *name* is shown to reviewers by design in M06; its local *path* must never be)
    always_secret = [DEVICE_KEYS['FLOOD-A'], key_hash, 'raw_payload', 'api_key_hash', 'instance/models',
                     'instance\\models', app.config['VISION_MODEL_PATH'], app.config['REPORT_UPLOAD_DIR'], '.jpg"']
    always_secret += [json.dumps(s)[1:-1] for s in always_secret]  # as they would appear inside JSON
    internal = ['PRIVATE-REPORT-TEXT', 'INTERNAL-NOTE', 'INTERNAL-ACTION', 'INTERNAL-RESOLUTION', *source_refs]
    urls = ['/api/hazards', '/api/hazards/1', f"/api/hazards/{submitted['incident_id']}", '/api/hazards?status=resolved',
            '/api/dashboard', '/api/notifications', '/api/iot/latest', '/api/reports',
            f"/api/reports/{submitted['id']}", '/api/hazards/1/status-history', '/api/hazards/1/investigations',
            '/api/hazards/1/response-actions', '/api/iot/devices']
    for who in ('citizen_a2', 'citizen_b', 'auth_b'):
        login(client, who)
        for url in urls:
            body = client.get(url).get_data(as_text=True)
            for secret in always_secret + internal:
                assert secret not in body, (who, url, secret)
    login(client, 'auth_a')  # managers see internal notes, but never credentials or storage paths
    for url in urls:
        body = client.get(url).get_data(as_text=True)
        for secret in always_secret:
            assert secret not in body, ('auth_a', url, secret)


# ============================================================================ dashboard over integrated state

def test_dashboard_reflects_integrated_state_and_stays_read_only(app, client, world, vision):
    for level in (3.3, 4.1):
        telemetry(client, 'FLOOD-A', water(level))
    telemetry(client, 'MOTION-B', {'sensor_type': 'tilt', 'value': 1.5, 'unit': '°'})
    report(client, world, 'citizen_b', 'road_damage', RED, district='b', lat='26.80')
    login(client, 'auth_a')
    client.post('/api/hazards/1/investigations', json={'note': 'n'})
    client.post('/api/hazards/1/response-actions', json={'action_type': 'monitor_area', 'description': 'watch'})

    def snapshot():
        with app.app_context():
            return ([(i.status, i.severity, i.report_count) for i in Incident.query.order_by(Incident.id)],
                    counts(app, Notification, SensorReading, IncidentStatusHistory),
                    [(d.status, d.enabled, d.last_seen) for d in IoTDevice.query.order_by(IoTDevice.id)])
    before = snapshot()

    login(client, 'admin')
    admin = client.get('/api/dashboard').get_json()
    assert admin['summary'] == {'total': 2, 'by_type': {'flood': 1, 'earthquake': 0, 'landslide': 0, 'road_damage': 1},
                                'by_severity': {'low': 0, 'medium': 1, 'high': 1, 'critical': 0}}
    flood = next(h for h in admin['hazards'] if h['event_type'] == 'flood')
    assert flood['response'] == {'notes': 1, 'open_actions': 1, 'actions': 1}
    assert {d['device_id'] for d in admin['devices']} == {'FLOOD-A', 'MOTION-A', 'MOTION-B'}
    assert admin['reports'][0]['ai_analysis']['label'] == 'road_damage'
    assert admin['statistics']['events']['by_status']['detected'] == 2
    filtered = client.get(f"/api/dashboard?district_id={world['d']['b']}").get_json()
    assert [h['event_type'] for h in filtered['hazards']] == ['road_damage']
    assert [d['device_id'] for d in filtered['devices']] == ['MOTION-B']

    login(client, 'auth_b')
    scoped = client.get('/api/dashboard').get_json()
    assert [h['event_type'] for h in scoped['hazards']] == ['road_damage']
    assert [d['device_id'] for d in scoped['devices']] == ['MOTION-B']
    assert scoped['devices'][0]['readings'][0]['value'] == 1.5
    login(client, 'citizen_a')
    citizen = client.get('/api/dashboard').get_json()
    assert [h['event_type'] for h in citizen['hazards']] == ['flood'] and 'reports' not in citizen
    assert citizen['unread_notifications'] == 2  # detected + escalated
    assert snapshot() == before
