"""M08: multi-signal risk engine — flood (M01 semantics + trend/corroboration), abnormal motion
(config-gated), landslide/road-damage evidence grades, multi-signal and cross-district rules,
hazard-event/notification integration, client-controlled input, read-only assessment API."""
import io
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image

from app.extensions import db
from app.models import Authority, CitizenReport, District, Incident, IoTDevice, Notification, River, User
from app.models.iot_device import SensorReading
from app.services import risk_engine, risk_service
from app.services.risk_engine import assess_flood, assess_motion, assess_visual, water_level_trend

T0 = datetime(2026, 10, 1, 10, 0, 0)


def R(value, minutes=0, quality='good', **extra):
    """A reading-like object for the pure rules."""
    return SimpleNamespace(value=value, recorded_at=T0 + timedelta(minutes=minutes), quality=quality, **extra)


def REPORT(reporter, status='submitted', ai_status='not_analyzed', ai_label=None, ai_confidence=None):
    return SimpleNamespace(reporter_id=reporter, status=status, ai_status=ai_status, ai_label=ai_label,
                           ai_confidence=ai_confidence)


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def world(app, tmp_path):
    app.config['REPORT_UPLOAD_DIR'] = str(tmp_path / 'reports')
    with app.app_context():
        a, b = District(name='District A', province='P'), District(name='District B', province='P')
        db.session.add_all([a, b])
        db.session.commit()
        auth_a = Authority(name='Auth A', category='water', district_id=a.id)
        auth_b = Authority(name='Auth B', category='water', district_id=b.id)
        river_a = River(name='River A', district_id=a.id, current_level=1.0, danger_level=4.0, status='normal')
        river_b = River(name='River B', district_id=b.id, current_level=1.0, danger_level=4.0, status='normal')
        db.session.add_all([auth_a, auth_b, river_a, river_b])
        db.session.commit()
        users = {}
        for name, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None), ('citizen_a2', 'citizen', a.id, None),
            ('citizen_b', 'citizen', b.id, None), ('auth_a', 'authority', a.id, auth_a.id),
            ('auth_b', 'authority', b.id, auth_b.id), ('admin', 'admin', None, None),
        ]:
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district_id,
                        authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        devices = {}
        for key, district, river, lat in [('FLOOD-A', a, river_a, 27.2), ('FLOOD-B', b, river_b, 26.9),
                                          ('MOTION-A', a, None, 27.3), ('MOTION-B', b, None, 26.8)]:
            device = IoTDevice(device_id=key, name=key.title(), district_id=district.id,
                               river_id=river.id if river else None, latitude=lat, longitude=85.9,
                               enabled=True, api_key_hash=IoTDevice.hash_api_key('k'))
            db.session.add(device)
            devices[key] = device
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'river_a': river_a.id, 'river_b': river_b.id,
                'u': {k: v.id for k, v in users.items()}, 'd': {k: v.id for k, v in devices.items()}}


def _telemetry(client, device, *readings, timestamp=None, **extra):
    body = {'readings': [dict(r) for r in readings], **extra}
    if timestamp:
        body['timestamp'] = timestamp
    return client.post('/api/iot/telemetry', json=body, headers={'Authorization': f'Bearer {device}:k'})


def W(value):
    return {'sensor_type': 'water_level', 'value': value, 'unit': 'm'}


def V(value):
    return {'sensor_type': 'vibration', 'value': value, 'unit': 'mg'}


def TILT(value):
    return {'sensor_type': 'tilt', 'value': value, 'unit': '°'}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (120, 90, 60)).save(buf, format='JPEG')
    return buf.getvalue()


def _report(client, world, user, hazard_type='landslide', district='a', lat='27.20'):
    _login(client, user)
    response = client.post('/api/reports', content_type='multipart/form-data', data={
        'hazard_type': hazard_type, 'district_id': str(world[district]), 'latitude': lat, 'longitude': '85.90',
        'image': (io.BytesIO(_jpeg()), 'p.jpg', 'image/jpeg')})
    assert response.status_code == 201, response.get_json()
    return response.get_json()['report']


def _set_ai(app, report_id, label, confidence=0.9, status='completed'):
    with app.app_context():
        report = db.session.get(CitizenReport, report_id)
        report.ai_status, report.ai_label, report.ai_confidence = status, label, confidence
        report.ai_model = 'google/siglip-base-patch16-224'
        db.session.commit()


def _assessment(client, event_id, user='admin'):
    _login(client, user)
    response = client.get(f'/api/hazards/{event_id}/assessment')
    assert response.status_code == 200, response.get_json()
    return response.get_json()['assessments']


def _types(app, **filters):
    with app.app_context():
        return sorted(n.type for n in Notification.query.filter_by(**filters))


# ---------------------------------------------------------------- flood: pure rules

class TestFloodRules:
    @pytest.mark.parametrize('level, expected, action, severity', [
        (2.0, 'normal', 'none', None),          # 50%
        (3.19, 'normal', 'none', None),         # 79.75%: M01 boundary unchanged
        (3.2, 'rising', 'report_event', 'medium'),  # 80%
        (3.99, 'rising', 'report_event', 'medium'),
        (4.0, 'flooding', 'report_event', 'high'),  # 100%
    ])
    def test_m01_semantics_preserved(self, level, expected, action, severity):
        a = assess_flood(level, 4.0, [])
        assert (a.level, a.action, a.severity) == (expected, action, severity)
        assert a.hazard_type == 'flood' and a.sources == ['iot']

    @pytest.mark.parametrize('danger', [None, 0, -1])
    def test_unknown_never_acts(self, danger):
        a = assess_flood(9.0, danger, [R(9.0)])
        assert (a.level, a.action) == ('unknown', 'none')
        assert any('insufficient evidence' in r for r in a.reasons)

    def test_trend_calculation(self):
        trend = water_level_trend([R(1.00, 0), R(1.10, 5), R(1.20, 10)])
        assert trend == {'trend': 'increasing', 'readings': 3, 'change_m': 0.2, 'span_seconds': 600.0,
                         'rate_m_per_hour': 1.2}
        assert water_level_trend([R(1.2, 0), R(1.1, 5), R(1.0, 10)])['trend'] == 'decreasing'
        assert water_level_trend([R(1.0, 0), R(1.02, 5), R(1.01, 10)])['trend'] == 'steady'

    def test_trend_uses_timestamps_not_row_order(self):
        assert water_level_trend([R(1.20, 10), R(1.00, 0), R(1.10, 5)])['change_m'] == 0.2

    @pytest.mark.parametrize('readings', [
        [R(1.0, 0), R(1.5, 10)],                    # too few
        [R(1.0, 0), R(1.2, 1), R(1.4, 2)],          # span < 5 min
        [R(1.0, 0), R(5.0, 5, 'bad'), R(1.4, 10, 'suspect')],  # only one good reading
    ])
    def test_trend_insufficient(self, readings):
        assert water_level_trend(readings)['trend'] == 'insufficient'

    def test_bad_quality_ignored_and_does_not_corroborate(self):
        a = assess_flood(3.4, 4.0, [R(3.4, 0), R(4.5, 1, 'bad'), R(4.6, 2, 'suspect')])
        assert a.evidence['valid_readings'] == 1 and a.evidence['ignored_readings'] == 2
        assert a.evidence['corroborating_readings'] == 1 and a.level == 'rising'

    def test_repeated_readings_corroborate(self):
        a = assess_flood(3.5, 4.0, [R(3.3, 0), R(3.4, 5), R(3.5, 10)])
        assert a.evidence['corroborating_readings'] == 3
        assert any("3 valid readings in the window agree on 'rising'" in r for r in a.reasons)

    def test_rising_trend_below_threshold_is_not_a_prediction(self):
        a = assess_flood(3.0, 4.0, [R(2.0, 0), R(2.5, 10), R(3.0, 20)])
        assert a.evidence['trend']['trend'] == 'increasing'
        assert (a.level, a.action, a.severity) == ('normal', 'none', None)


# ---------------------------------------------------------------- flood: pipeline

class TestFloodPipeline:
    def test_normal_water_no_event(self, app, client, world):
        assert _telemetry(client, 'FLOOD-A', W(2.0)).status_code == 201
        with app.app_context():
            assert Incident.query.count() == 0 and Notification.query.count() == 0

    def test_rising_then_repeated_then_flooding(self, app, client, world):
        for level in (3.3, 3.4, 3.5):
            assert _telemetry(client, 'FLOOD-A', W(level)).status_code == 201
        with app.app_context():
            event = Incident.query.one()  # no duplicate events
            assert (event.event_type, event.severity, event.source, event.report_count) == ('flood', 'medium', 'iot', 3)
            assert event.river_id == world['river_a'] and event.district_id == world['a']
        assert _types(app, user_id=world['u']['citizen_a']) == ['hazard_detected']  # once, not per reading
        _telemetry(client, 'FLOOD-A', W(4.2))
        _telemetry(client, 'FLOOD-A', W(4.3))
        with app.app_context():
            assert Incident.query.one().severity == 'high'
        assert _types(app, user_id=world['u']['citizen_a']) == ['hazard_detected', 'hazard_escalated']

    @pytest.mark.parametrize('reading', [
        {'sensor_type': 'water_level', 'value': 340, 'unit': 'cm'},   # wrong unit: still metres only
        {'sensor_type': 'water_level', 'value': 51, 'unit': 'm'},     # out of range
        {'sensor_type': 'water_level', 'value': 'high', 'unit': 'm'},
    ])
    def test_invalid_reading_rejected_no_event(self, app, client, world, reading):
        assert _telemetry(client, 'FLOOD-A', reading).status_code == 400
        with app.app_context():
            assert Incident.query.count() == 0 and SensorReading.query.count() == 0

    def test_client_cannot_set_risk_severity_source(self, app, client, world):
        reading = {**W(3.3), 'severity': 'critical', 'risk_level': 'critical', 'confidence': 0.99,
                   'quality': 'good', 'source': 'authority'}
        assert _telemetry(client, 'FLOOD-A', reading, severity='critical', source='authority').status_code == 201
        with app.app_context():
            event = Incident.query.one()
            assert (event.severity, event.source, event.confidence) == ('medium', 'iot', None)

    def test_trend_assessment_from_stored_timestamps(self, app, client, world):
        now = datetime.utcnow()
        for minutes, level in ((10, 1.0), (5, 1.1), (0, 1.2)):
            _telemetry(client, 'FLOOD-A', W(level), timestamp=(now - timedelta(minutes=minutes)).isoformat() + 'Z')
        with app.app_context():
            a = risk_service.flood_assessment(db.session.get(River, world['river_a']), 1.2)
            assert a.evidence['trend']['trend'] == 'increasing' and a.evidence['trend']['change_m'] == 0.2
            assert a.level == 'normal' and a.action == 'none'

    def test_other_river_readings_do_not_count(self, app, client, world):
        for level in (3.6, 3.7, 3.8):
            _telemetry(client, 'FLOOD-B', W(level))
        with app.app_context():
            a = risk_service.flood_assessment(db.session.get(River, world['river_a']), 1.0)
            assert a.evidence['valid_readings'] == 0 and a.level == 'normal'
            assert Incident.query.one().district_id == world['b']
        assert _types(app, user_id=world['u']['citizen_a']) == []


# ---------------------------------------------------------------- seismic / abnormal motion

class TestMotion:
    def test_disabled_by_default(self, app, client, world):
        assert app.config['MOTION_VIBRATION_THRESHOLD_MG'] is None
        for _ in range(5):
            assert _telemetry(client, 'MOTION-A', V(900), TILT(30)).status_code == 201
        with app.app_context():
            assert Incident.query.count() == 0
            a = risk_service.motion_assessment(db.session.get(IoTDevice, world['d']['MOTION-A']))
            assert a.level == 'uncharacterized' and a.action == 'none'
            assert any('hardware characterization required' in r for r in a.reasons)

    def test_repeated_vibration_creates_one_abnormal_motion_event(self, app, client, world):
        app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300
        for _ in range(2):
            _telemetry(client, 'MOTION-A', V(450))
        with app.app_context():
            assert Incident.query.count() == 0  # 2 < MOTION_MIN_READINGS
        for _ in range(3):
            _telemetry(client, 'MOTION-A', V(450))
        with app.app_context():
            event = Incident.query.one()
            assert (event.event_type, event.severity, event.source, event.status) == \
                ('earthquake', 'medium', 'iot', 'detected')
            # INTENTIONAL ARCHITECTURE CHANGE (Phase 4A): one Device Event = one piece of evidence;
            # continued ACTIVE readings no longer merge into the Incident on every telemetry.
            assert event.district_id == world['a'] and event.report_count == 1
            assert event.title == 'Abnormal ground motion signal: Motion-A'
            assert 'not a prediction' in event.description and 'magnitude' in event.description
            assert 'predict' not in event.title.lower()
        assert _types(app, type='hazard_escalated') == []  # repeated evidence never escalates

    def test_single_spike_ignored(self, app, client, world):
        app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300
        _telemetry(client, 'MOTION-A', V(10))
        _telemetry(client, 'MOTION-A', V(990))
        _telemetry(client, 'MOTION-A', V(12))
        with app.app_context():
            assert Incident.query.count() == 0

    def test_tilt_change_rule(self, app, client, world):
        app.config['MOTION_TILT_CHANGE_THRESHOLD_DEG'] = 5
        for value in (0.5, 0.8, 7.0):
            _telemetry(client, 'MOTION-A', TILT(value))
        with app.app_context():
            assert Incident.query.one().event_type == 'earthquake'

    @pytest.mark.parametrize('reading', [V(1500), V(-1), TILT(200), TILT(-181),
                                         {'sensor_type': 'vibration', 'value': 500, 'unit': 'g'},
                                         {'sensor_type': 'acceleration', 'value': 2, 'unit': 'g'}])
    def test_invalid_or_unsupported_values_rejected(self, app, client, world, reading):
        app.config.update(MOTION_VIBRATION_THRESHOLD_MG=1, MOTION_TILT_CHANGE_THRESHOLD_DEG=1)
        for _ in range(3):
            assert _telemetry(client, 'MOTION-A', reading).status_code == 400
        with app.app_context():
            assert Incident.query.count() == 0 and SensorReading.query.count() == 0

    def test_threshold_above_validation_cap_disables_rule(self):
        a = assess_motion([R(999, i) for i in range(5)], [], vibration_threshold_mg=1500)
        assert a.level == 'uncharacterized' and a.action == 'none'
        assert any('telemetry validation cap' in r for r in a.reasons)

    def test_bad_quality_motion_ignored(self):
        a = assess_motion([R(800, 0, 'bad'), R(800, 1, 'bad'), R(800, 2, 'suspect'), R(800, 3)], [],
                          vibration_threshold_mg=300)
        assert a.level == 'normal_motion' and a.evidence['ignored_readings'] == 3

    def test_other_district_device_stays_in_its_district(self, app, client, world):
        app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300
        for _ in range(3):
            _telemetry(client, 'MOTION-B', V(500))
        with app.app_context():
            assert Incident.query.one().district_id == world['b']
        assert _types(app, user_id=world['u']['citizen_a']) == []
        assert _types(app, user_id=world['u']['citizen_b']) == ['hazard_detected']


# ---------------------------------------------------------------- landslide / road damage

class TestVisualRules:
    @pytest.mark.parametrize('hazard', ['landslide', 'road_damage'])
    @pytest.mark.parametrize('reports, level', [
        ([], 'insufficient'),
        ([REPORT(1)], 'single_report'),
        ([REPORT(1, ai_status='completed', ai_label='unknown', ai_confidence=0.3)], 'single_report'),  # low score
        ([REPORT(1, ai_status='failed')], 'single_report'),
        ([REPORT(1, ai_status='completed', ai_label='HAZARD', ai_confidence=0.9)], 'supported'),
        ([REPORT(1), REPORT(2)], 'supported'),
        ([REPORT(1), REPORT(1), REPORT(1)], 'single_report'),  # duplicate evidence from one person
        ([REPORT(1, ai_status='completed', ai_label='HAZARD'), REPORT(2)], 'corroborated'),
        ([REPORT(1, status='rejected', ai_status='completed', ai_label='HAZARD'), REPORT(2)], 'single_report'),
    ])
    def test_grades(self, hazard, reports, level):
        reports = [SimpleNamespace(**{**vars(r), 'ai_label': hazard if r.ai_label == 'HAZARD' else r.ai_label})
                   for r in reports]  # copies: parametrized objects are shared between cases
        a = assess_visual(hazard, reports)
        assert a.level == level
        assert (a.action, a.severity) == ('none', None)  # never escalates or confirms

    def test_conflicting_ai_flags_review_without_raising(self):
        a = assess_visual('road_damage', [REPORT(1, ai_status='completed', ai_label='landslide', ai_confidence=0.95)])
        assert a.level == 'single_report' and a.evidence['ai_conflict'] == 1
        assert any('different hazard type' in r for r in a.reasons)
        assert 'vision_ai' not in a.sources

    def test_sources_and_authority(self):
        a = assess_visual('landslide', [REPORT(1, ai_status='completed', ai_label='landslide')], authority_source=True)
        assert a.sources == ['citizen_report', 'vision_ai', 'authority']
        assert any('not probabilities' in r for r in a.reasons)


class TestVisualPipeline:
    @pytest.mark.parametrize('hazard', ['landslide', 'road_damage'])
    def test_citizen_plus_ai_corroborates_but_cannot_confirm(self, app, client, world, hazard):
        first = _report(client, world, 'citizen_a', hazard)
        second = _report(client, world, 'citizen_a2', hazard, lat='27.21')
        assert first['incident_id'] == second['incident_id']
        _set_ai(app, first['id'], hazard, 0.99)
        [a] = _assessment(client, first['incident_id'])
        assert a['level'] == 'corroborated' and a['evidence']['max_ai_agree_confidence'] == 0.99
        with app.app_context():
            event = db.session.get(Incident, first['incident_id'])
            assert (event.status, event.severity) == ('detected', 'medium')
        for kind in ('hazard_escalated', 'hazard_confirmed'):
            assert _types(app, type=kind) == []

    def test_ai_unknown_and_disagreement(self, app, client, world):
        report = _report(client, world, 'citizen_a', 'road_damage')
        _set_ai(app, report['id'], 'unknown', 0.31)
        [a] = _assessment(client, report['incident_id'])
        assert a['level'] == 'single_report' and a['evidence']['ai_unknown'] == 1
        _set_ai(app, report['id'], 'landslide', 0.9)
        [a] = _assessment(client, report['incident_id'])
        assert a['level'] == 'single_report' and a['evidence']['ai_conflict'] == 1

    def test_reports_from_other_district_do_not_combine(self, app, client, world):
        a_report = _report(client, world, 'citizen_a', 'landslide')
        b_report = _report(client, world, 'citizen_b', 'landslide', district='b', lat='27.20')
        assert a_report['incident_id'] != b_report['incident_id']
        _set_ai(app, b_report['id'], 'landslide')
        [a] = _assessment(client, a_report['incident_id'])
        assert a['evidence']['distinct_reporters'] == 1 and a['evidence']['ai_agree'] == 0
        assert a['district_id'] == world['a']


# ---------------------------------------------------------------- assessment API + security

class TestAssessmentApi:
    def test_authorization(self, app, client, world):
        event_id = _report(client, world, 'citizen_a')['incident_id']
        assert client.get(f'/api/hazards/{event_id}/assessment').status_code == 403  # citizen
        _login(client, 'auth_b')
        assert client.get(f'/api/hazards/{event_id}/assessment').status_code == 403  # other district
        _login(client, 'auth_a')
        assert client.get(f'/api/hazards/{event_id}/assessment').status_code == 200
        assert client.get('/api/hazards/99999/assessment').status_code == 404
        assert client.post(f'/api/hazards/{event_id}/assessment').status_code == 405  # read-only
        client.get('/auth/logout')
        assert client.get(f'/api/hazards/{event_id}/assessment').status_code == 401

    def test_query_params_cannot_inject_risk(self, app, client, world):
        event_id = _report(client, world, 'citizen_a')['incident_id']
        _login(client, 'admin')
        body = client.get(f'/api/hazards/{event_id}/assessment?level=corroborated&severity=critical'
                          '&confidence=0.99').get_json()
        assert body['assessments'][0]['level'] == 'single_report'
        with app.app_context():
            assert db.session.get(Incident, event_id).severity == 'medium'

    def test_no_private_data(self, app, client, world):
        _login(client, 'citizen_a')
        client.post('/api/reports', content_type='multipart/form-data', data={
            'hazard_type': 'landslide', 'district_id': str(world['a']), 'description': 'secret note',
            'image': (io.BytesIO(_jpeg()), 'p.jpg', 'image/jpeg')})
        for level in (3.3, 3.4):
            _telemetry(client, 'FLOOD-A', W(level))
        with app.app_context():
            ids = [i.id for i in Incident.query]
        _login(client, 'admin')
        for event_id in ids:
            body = client.get(f'/api/hazards/{event_id}/assessment').get_data(as_text=True)
            for secret in ('secret note', 'image_filename', '.jpg', 'reporter_id', 'email', 'raw_payload',
                           'api_key', 'source_reference', 'citizen_a'):
                assert secret not in body

    def test_flood_and_motion_assessments(self, app, client, world):
        app.config['MOTION_VIBRATION_THRESHOLD_MG'] = 300
        for level in (3.3, 3.4, 3.5):
            _telemetry(client, 'FLOOD-A', W(level))
        for _ in range(3):
            _telemetry(client, 'MOTION-A', V(400))
        with app.app_context():
            flood = Incident.query.filter_by(event_type='flood').one().id
            quake = Incident.query.filter_by(event_type='earthquake').one().id
        [f] = _assessment(client, flood, 'auth_a')
        assert f['level'] == 'rising' and f['evidence']['corroborating_readings'] == 3
        motion = _assessment(client, quake, 'auth_a')
        assert [m['evidence']['device'] for m in motion] == ['Flood-A', 'Motion-A']  # devices in district A only
        assert motion[1]['level'] == 'elevated_motion'


# ---------------------------------------------------------------- architecture

class TestArchitecture:
    def test_engine_and_service_never_touch_notifications(self):
        for module in (risk_engine, risk_service):
            names = set(vars(module))
            assert not names & {'Notification', 'notification_service', 'notify_hazard', 'create_notification'}
        assert 'db' not in vars(risk_engine) and 'Incident' not in vars(risk_engine)

    def test_notifications_come_from_notification_service_via_events(self, app, client, world, monkeypatch):
        from app.services import notification_service
        calls = []
        original = notification_service.notify_hazard

        def spy(incident, ntype, exclude_user_ids=()):
            calls.append((incident.event_type, ntype))
            return original(incident, ntype, exclude_user_ids)
        monkeypatch.setattr(notification_service, 'notify_hazard', spy)
        _telemetry(client, 'FLOOD-A', W(3.3))
        _telemetry(client, 'FLOOD-A', W(4.1))
        assert calls == [('flood', 'hazard_detected'), ('flood', 'hazard_escalated')]
        with app.app_context():
            assert all(n.incident_id for n in Notification.query)

    def test_assessment_serializes(self):
        d = assess_flood(3.3, 4.0, [R(3.3)]).to_dict()
        assert json.loads(json.dumps(d))['level'] == 'rising'
        assert set(d) == {'hazard_type', 'level', 'action', 'severity', 'reasons', 'evidence', 'sources',
                          'district_id', 'assessed_at'}
