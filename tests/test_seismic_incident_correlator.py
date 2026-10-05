"""Phase 4A tests: Seismic Device Event -> Incident correlation.

Full pipeline: POST /api/iot/telemetry -> state machine -> correlator -> hazard_event_service
-> Incident + hazard_detected notifications. The motion assessment is scripted (elevated/normal)
so tests don't depend on the 60 s wall-clock window; reading timestamps drive the state machine.
"""
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta

import pytest

from app.config import TestingConfig
from app.extensions import db
from app.models import Authority, District, Incident, IoTDevice, Notification, River, SensorReading, User
from app.models.seismic_event_state import SeismicEventState
from app.services import hazard_event_service, notification_service, risk_service
from app.services.risk_engine import RiskAssessment
from app.services.seismic_incident_correlator import correlate_device_event
from app.services.seismic_state import SeismicDeviceEvent, SeismicState, StateTransition
from app.services.seismic_state_persistence import load_state

T0 = datetime(2026, 10, 1, 10, 0, 0)
ACTIVE = ('detected', 'investigating', 'confirmed', 'response')


def ELEVATED(district_id=None):
    return RiskAssessment('earthquake', 'elevated_motion', action='report_event', severity='medium',
                          reasons=['Abnormal ground-motion signal: 3 vibration readings >= 300 mg'],
                          evidence={'max_vibration_mg': 400.0, 'vibration_over_threshold': 3},
                          sources=['iot'], district_id=district_id)


def NORMAL(district_id=None):
    return RiskAssessment('earthquake', 'normal_motion', reasons=['normal'],
                          evidence={'max_vibration_mg': 20.0}, sources=['iot'], district_id=district_id)


@pytest.fixture
def world(app):
    with app.app_context():
        sindhuli, other = District(name='Sindhuli', province='P'), District(name='Other', province='P')
        db.session.add_all([sindhuli, other])
        db.session.commit()
        police = Authority(name='Sindhuli District Police', category='police', district_id=sindhuli.id)
        db.session.add(police)
        db.session.commit()
        for name, role, district_id, authority_id in [
                ('citizen', 'citizen', sindhuli.id, None), ('citizen2', 'citizen', sindhuli.id, None),
                ('outsider', 'citizen', other.id, None), ('admin', 'admin', None, None),
                ('police', 'authority', None, police.id)]:  # reached through its Authority's district
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district_id,
                        authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
        for key in ('ESP32-SEISMIC-001', 'ESP32-SEISMIC-002'):
            # Real hardware: no coordinates configured
            db.session.add(IoTDevice(device_id=key, name=key, district_id=sindhuli.id, enabled=True,
                                     latitude=None, longitude=None, api_key_hash=IoTDevice.hash_api_key('k')))
        db.session.commit()
        return {'district': sindhuli.id, 'recipients': 4}  # 2 Sindhuli citizens + Sindhuli authority + admin


@pytest.fixture
def script(monkeypatch):
    """Next motion assessment returned for the device: script['ESP32-SEISMIC-001'] = ELEVATED."""
    levels = {}
    monkeypatch.setattr(risk_service, 'motion_assessment',
                        lambda device, now=None: levels[device.device_id](device.district_id))
    return levels


def send(client, script, level, at, device='ESP32-SEISMIC-001'):
    script[device] = level
    r = client.post('/api/iot/telemetry', headers={'Authorization': f'Bearer {device}:k'},
                    json={'timestamp': at.isoformat() + 'Z',
                          'readings': [{'sensor_type': 'vibration', 'value': 400.0, 'unit': 'mg'}]})
    assert r.status_code == 201, r.get_json()


def quakes():
    return Incident.query.filter_by(event_type='earthquake').order_by(Incident.id).all()


def detected_count():
    return Notification.query.filter_by(type='hazard_detected').count()


def state(device='ESP32-SEISMIC-001'):
    return SeismicEventState.query.join(IoTDevice).filter(IoTDevice.device_id == device).one()


def start_event(client, script, at=T0):
    send(client, script, ELEVATED, at)
    [incident] = quakes()
    return incident.id


class TestDeviceEventToIncident:
    def test_a_first_event_creates_one_incident_and_notifies(self, app, client, world, script):
        send(client, script, ELEVATED, T0)
        with app.app_context():
            [incident] = quakes()
            assert (incident.severity, incident.source, incident.status) == ('medium', 'iot', 'detected')
            assert incident.district_id == world['district']
            assert incident.latitude is None and incident.longitude is None
            assert state().state == 'active' and state().active_incident_id == incident.id
            assert detected_count() == world['recipients']
            assert {n.incident_id for n in Notification.query} == {incident.id}

    def test_b_continuation_same_incident_no_new_notification(self, app, client, world, script):
        incident_id = start_event(client, script)
        for i in range(1, 4):
            send(client, script, ELEVATED, T0 + timedelta(seconds=10 * i))
        with app.app_context():
            assert [i.id for i in quakes()] == [incident_id]
            assert quakes()[0].report_count == 1  # continuation is not new evidence
            assert state().active_incident_id == incident_id
            assert detected_count() == world['recipients']

    def test_c_recovery_ends_event_but_never_resolves_incident(self, app, client, world, script):
        incident_id = start_event(client, script)
        for i in range(1, 4):  # MOTION_RECOVERY_WINDOWS defaults to 3
            send(client, script, NORMAL, T0 + timedelta(seconds=10 * i))
        with app.app_context():
            row = state()
            assert row.state == 'quiet' and row.active_incident_id is None
            incident = db.session.get(Incident, incident_id)
            assert incident.status in ACTIVE and incident.resolved_at is None
            assert Notification.query.count() == world['recipients']  # only the original alert

    def test_d_gap_entry_does_nothing_to_the_incident(self, app, client, world, script):
        incident_id = start_event(client, script)
        with app.app_context():
            device = IoTDevice.query.filter_by(device_id='ESP32-SEISMIC-001').one()
            event = load_state(device.id)
            gap = StateTransition(SeismicState.ACTIVE, SeismicState.TELEMETRY_GAP, gap_entered=True)
            assert correlate_device_event(device, event, ELEVATED(), gap) is None
            assert event.active_incident_id == incident_id

    def test_d_gap_then_normal_no_new_incident(self, app, client, world, script):
        incident_id = start_event(client, script)
        send(client, script, NORMAL, T0 + timedelta(minutes=10))  # > 300 s: gap entered, resumed as RECOVERY
        with app.app_context():
            assert state().state == 'recovery' and state().active_incident_id == incident_id
            assert [i.id for i in quakes()] == [incident_id]
            assert quakes()[0].status in ACTIVE
            assert detected_count() == world['recipients']

    def test_e_gap_resume_elevated_same_incident(self, app, client, world, script):
        incident_id = start_event(client, script)
        send(client, script, ELEVATED, T0 + timedelta(minutes=10))  # gap entered, resumed ACTIVE
        with app.app_context():
            assert state().state == 'active' and state().active_incident_id == incident_id
            assert [i.id for i in quakes()] == [incident_id]
            assert detected_count() == world['recipients']

    def _end_event(self, client, script, start):
        for i in range(1, 4):
            send(client, script, NORMAL, start + timedelta(seconds=10 * i))

    def test_f_new_event_reuses_same_device_incident_while_still_active(self, app, client, world, script):
        incident_id = start_event(client, script)
        self._end_event(client, script, T0)
        later = T0 + timedelta(minutes=1)  # no cooldown: timing is irrelevant, the lifecycle decides
        send(client, script, ELEVATED, later)
        with app.app_context():
            assert [i.id for i in quakes()] == [incident_id]
            assert quakes()[0].report_count == 2  # event #2 attached as evidence, no escalation
            assert quakes()[0].severity == 'medium'
            assert state().active_incident_id == incident_id
            assert detected_count() == world['recipients']

    def test_f_new_event_after_authority_resolved_creates_new_incident(self, app, client, world, script):
        first_id = start_event(client, script)
        self._end_event(client, script, T0)
        with app.app_context():
            first = db.session.get(Incident, first_id)
            hazard_event_service.escalate_to_investigating(first)
            hazard_event_service.confirm_event(first)
            hazard_event_service.resolve_event(first)  # authority lifecycle, not the Device Event
            resolved_alerts = Notification.query.filter_by(type='hazard_resolved').count()
        send(client, script, ELEVATED, T0 + timedelta(minutes=1))
        with app.app_context():
            first, second = quakes()
            assert first.id == first_id and first.status == 'resolved'
            assert second.status == 'detected' and state().active_incident_id == second.id
            assert detected_count() == 2 * world['recipients']
            assert Notification.query.filter_by(type='hazard_resolved').count() == resolved_alerts

    def test_g_same_district_other_device_is_not_merged(self, app, client, world, script):
        first_id = start_event(client, script)
        send(client, script, ELEVATED, T0 + timedelta(seconds=5), device='ESP32-SEISMIC-002')
        with app.app_context():
            first, second = quakes()
            assert first.id == first_id and first.report_count == 1
            assert state('ESP32-SEISMIC-002').active_incident_id == second.id
            assert state().active_incident_id == first_id

    def test_h_lost_event_start_race_creates_nothing(self, app, client, world, script, monkeypatch):
        """Request B loaded QUIET before request A committed its event start (the race window)."""
        incident_id = start_event(client, script)
        stale = lambda device_id: SeismicDeviceEvent()  # B's pre-commit snapshot: QUIET
        monkeypatch.setattr(risk_service, 'load_state', stale)
        send(client, script, ELEVATED, T0 + timedelta(seconds=1))
        with app.app_context():
            assert [i.id for i in quakes()] == [incident_id]
            assert quakes()[0].report_count == 1  # B did not correlate a second event start
            assert state().state == 'active' and state().active_incident_id == incident_id
            assert detected_count() == world['recipients']
            assert SensorReading.query.count() == 2  # B's reading is still stored

    def test_l_failure_rolls_back_reading_state_incident_and_notifications(self, app, client, world, script,
                                                                            monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError('forced correlation failure')
        monkeypatch.setattr(notification_service, 'notify_hazard_detected', boom)
        with pytest.raises(RuntimeError):
            send(client, script, ELEVATED, T0)
        with app.app_context():
            db.session.remove()
            assert SensorReading.query.count() == 0
            assert SeismicEventState.query.count() == 0
            assert Incident.query.count() == 0 and Notification.query.count() == 0


def test_h_concurrent_event_start_two_connections(tmp_path, monkeypatch):
    """Two real threads/connections both load QUIET, then both try to start the Device Event."""
    from app import create_app
    monkeypatch.setattr(TestingConfig, 'SQLALCHEMY_DATABASE_URI', f"sqlite:///{tmp_path / 'race.db'}")
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        district = District(name='Sindhuli', province='P')
        db.session.add(district)
        db.session.commit()
        user = User(username='citizen', email='c@t.np', role='citizen', district_id=district.id)
        user.set_password('pw')
        device = IoTDevice(device_id='ESP32-SEISMIC-001', name='S1', district_id=district.id, enabled=True,
                           api_key_hash=IoTDevice.hash_api_key('k'))
        db.session.add_all([user, device])
        db.session.commit()
        device_pk = device.id
        load_state(device_pk)
        db.session.add(SensorReading(device_id=device_pk, sensor_type='vibration', value=400.0, unit='mg',
                                     recorded_at=T0, received_at=T0))
        db.session.commit()

    monkeypatch.setattr(risk_service, 'motion_assessment', lambda device, now=None: ELEVATED(device.district_id))
    both_loaded = threading.Barrier(2, timeout=10)
    real_load = risk_service.load_state

    def load_then_wait(device_id):
        event = real_load(device_id)
        both_loaded.wait()  # both requests now hold a QUIET snapshot
        return event
    monkeypatch.setattr(risk_service, 'load_state', load_then_wait)

    errors = []

    def request():
        try:
            with app.app_context():
                risk_service.evaluate_motion_with_state_machine(db.session.get(IoTDevice, device_pk))
                db.session.commit()
        except Exception as e:  # pragma: no cover - surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=request) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not errors, errors

    with app.app_context():
        [incident] = Incident.query.all()
        row = SeismicEventState.query.one()
        assert row.state == 'active' and row.active_incident_id == incident.id
        assert Notification.query.filter_by(type='hazard_detected').count() == 1
        db.drop_all()


class TestRegressions:
    def test_i_water_level_never_runs_the_seismic_correlator(self, app, client, monkeypatch):
        from app.models import River
        calls = []
        monkeypatch.setattr(risk_service, 'correlate_device_event', lambda *a: calls.append(a))
        with app.app_context():
            district = District(name='Flood D', province='P')
            db.session.add(district)
            db.session.commit()
            river = River(name='R', district_id=district.id, current_level=1.0, danger_level=4.0, status='normal')
            device = IoTDevice(device_id='FLOOD-1', name='F', district_id=district.id, enabled=True,
                               api_key_hash=IoTDevice.hash_api_key('k'))
            db.session.add_all([river, device])
            db.session.commit()
            device.river_id = river.id
            db.session.commit()
        for level in (3.3, 3.4, 3.5):
            r = client.post('/api/iot/telemetry', headers={'Authorization': 'Bearer FLOOD-1:k'},
                            json={'readings': [{'sensor_type': 'water_level', 'value': level, 'unit': 'm'}]})
            assert r.status_code == 201
        with app.app_context():
            assert Incident.query.filter_by(event_type='flood').count() == 1
            assert Incident.query.filter_by(event_type='earthquake').count() == 0
            assert SeismicEventState.query.count() == 0
        assert calls == []


class TestExistingEmergencyAlert:
    """DETECTED -> existing notifications + /api/emergency/active (banner + sound). NOT DETECTED -> nothing."""

    @pytest.fixture(autouse=True)
    def demo_config(self, app):
        app.config.update(MOTION_VIBRATION_THRESHOLD_MG=85, EMERGENCY_MIN_SEVERITY='medium')  # as in .env

    def _feed(self, client, user='citizen'):
        client.get('/auth/logout')
        path = '/auth/authority/login' if user == 'police' else '/auth/login'
        client.post(path, data={'username': user, 'password': 'pw'})
        body = client.get('/api/emergency/active').get_json()
        client.get('/auth/logout')
        return body

    def _alerts(self, client, user='citizen'):
        return self._feed(client, user)['alerts']

    def _real(self, client, mg, device='ESP32-SEISMIC-001'):
        """Unscripted: the real risk engine on real readings."""
        r = client.post('/api/iot/telemetry', headers={'Authorization': f'Bearer {device}:k'},
                        json={'readings': [{'sensor_type': 'vibration', 'value': mg, 'unit': 'mg'}]})
        assert r.status_code == 201

    def _recipients(self):
        return {db.session.get(User, n.user_id).username
                for n in Notification.query.filter_by(type='hazard_detected')}

    def test_confirmed_motion_alerts_authority_and_citizens_only(self, app, client, world):
        for mg in (120, 150, 200):
            self._real(client, mg)
        with app.app_context():
            [incident] = quakes()
            assert (incident.event_type, incident.severity, incident.source) == ('earthquake', 'medium', 'iot')
            assert self._recipients() == {'citizen', 'citizen2', 'police', 'admin'}  # not 'outsider'
            incident_id = incident.id
        for user in ('citizen', 'police'):
            [alert] = self._alerts(client, user)
            assert alert['type'] == 'hazard_detected' and alert['hazard']['id'] == incident_id
        assert self._alerts(client, 'outsider') == []

    def test_continued_motion_one_alert_only(self, app, client, world):
        for _ in range(20):
            self._real(client, 300)
        with app.app_context():
            assert len(quakes()) == 1 and detected_count() == world['recipients']
        assert len(self._alerts(client)) == 1

    @pytest.mark.parametrize('values', [(5, 8, 6, 7, 5), (60, 84, 70, 80, 84.9)],
                             ids=['stationary', 'below-threshold'])
    def test_no_hazard_nothing(self, app, client, world, values):
        for mg in values:
            self._real(client, mg)
        with app.app_context():
            assert Incident.query.count() == 0 and Notification.query.count() == 0
        assert self._alerts(client) == [] and self._alerts(client, 'police') == []

    def test_two_spikes_are_not_an_event(self, app, client, world):
        for mg in (500, 10, 500):  # MOTION_MIN_READINGS = 3
            self._real(client, mg)
        with app.app_context():
            assert Incident.query.count() == 0

    def test_flood_reaches_the_same_alert(self, app, client, world):
        with app.app_context():
            river = River(name='Kamala', district_id=world['district'], current_level=1.0, danger_level=4.0,
                          status='normal')
            db.session.add(river)
            db.session.commit()
            db.session.add(IoTDevice(device_id='FLOOD-1', name='F', district_id=world['district'],
                                     river_id=river.id, enabled=True, api_key_hash=IoTDevice.hash_api_key('k')))
            db.session.commit()
        for level in (3.3, 3.4, 3.5):
            r = client.post('/api/iot/telemetry', headers={'Authorization': 'Bearer FLOOD-1:k'},
                            json={'readings': [{'sensor_type': 'water_level', 'value': level, 'unit': 'm'}]})
            assert r.status_code == 201
        with app.app_context():
            [flood] = Incident.query.filter_by(event_type='flood').all()
            assert self._recipients() == {'citizen', 'citizen2', 'police', 'admin'}
            flood_id = flood.id
        [alert] = self._alerts(client, 'police')
        assert alert['hazard']['id'] == flood_id and alert['hazard']['event_type'] == 'flood'

    def test_without_vapid_keys_alert_still_works(self, app, client, world):
        app.config.update(VAPID_PUBLIC_KEY=None, VAPID_PRIVATE_KEY=None)
        for mg in (120, 150, 200):
            self._real(client, mg)
        assert len(self._alerts(client)) == 1

    def _browser(self, responses, audio):
        out = subprocess.run(['node', os.path.join(os.path.dirname(__file__), 'emergency_alarm_harness.js')],
                             input=json.dumps({'responses': responses, 'audio': audio}),
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_browser_banner_appears_and_sound_fires_once(self, app, client, world):
        """The real emergency.js fed with the real API bodies: a quiet poll, then the same alert on 3 polls."""
        quiet = self._feed(client)
        for mg in (120, 150, 200):
            self._real(client, mg)
        active = self._feed(client)
        assert self._browser([quiet, active, active, active], 'running') == [
            {'banner': False, 'alarms': 0, 'blocked': False},
            {'banner': True, 'alarms': 1, 'blocked': False},
            {'banner': True, 'alarms': 1, 'blocked': False},
            {'banner': True, 'alarms': 1, 'blocked': False}]

    def test_browser_autoplay_blocked_shows_play_button(self, app, client, world):
        for mg in (120, 150, 200):
            self._real(client, mg)
        assert self._browser([self._feed(client)], 'suspended') == [{'banner': True, 'alarms': 0, 'blocked': True}]
