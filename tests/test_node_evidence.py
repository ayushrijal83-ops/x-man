"""M-LIVE-02: server-side camera-node field evidence (POST /api/iot/evidence).

No phone and no hardware: the future Android field node is simulated with the test client. Covers
device auth hardening, the camera_node boundary, the metadata allow-list, frame sanitizing,
idempotency, capture-time / GPS plausibility, the hold policy, the per-device rate limit (including
concurrent requests), server AI corroboration, hazard/notification integration, frame authorization
and Super Admin provisioning of the new device kind.
"""
import io
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta

import pytest
from flask import g
from PIL import Image

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import (AuditLog, Authority, District, Incident, IoTDevice, NodeEvidence,
                        Notification, PushSubscription, SensorReading, User)
from app.models.incident_response import IncidentStatusHistory
from app.services import (admin_service, citizen_report_service, emergency_dispatcher, hazard_event_service,
                          risk_service, vision_service)

SITE = (27.7000, 85.3000)  # registered camera-node location (District A)
NEAR = (27.7010, 85.3010)  # ~150 m away
FAR = (27.5000, 85.3000)  # ~22 km away ("District B")
STORED = re.compile(r'^[0-9a-f]{32}\.jpg$')


@pytest.fixture(autouse=True)
def dirs(app, tmp_path):
    app.config['EVIDENCE_UPLOAD_DIR'] = str(tmp_path / 'evidence')
    app.config['REPORT_UPLOAD_DIR'] = str(tmp_path / 'reports')
    return tmp_path / 'evidence'


def _device(device_id, district_id, kind='camera_node', coords=SITE, **extra):
    key = IoTDevice.generate_api_key()
    device = IoTDevice(device_id=device_id, name=f'{device_id} node', district_id=district_id, kind=kind,
                       latitude=coords[0] if coords else None, longitude=coords[1] if coords else None,
                       location_description='Slope above the highway', api_key_hash=IoTDevice.hash_api_key(key),
                       status='active', enabled=True, **extra)
    db.session.add(device)
    db.session.commit()
    return key


@pytest.fixture
def world(app):
    a, b = District(name='District A', province='P'), District(name='District B', province='P')
    db.session.add_all([a, b])
    db.session.commit()
    auth_a = Authority(name='Auth A', category='disaster', district_id=a.id)
    auth_b = Authority(name='Auth B', category='disaster', district_id=b.id)
    db.session.add_all([auth_a, auth_b])
    db.session.commit()
    users = {}
    for username, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None), ('citizen_b', 'citizen', b.id, None),
            ('auth_a', 'authority', a.id, auth_a.id), ('auth_b', 'authority', b.id, auth_b.id),
            ('admin', 'admin', None, None)]:
        user = User(username=username, email=f'{username}@t.np', role=role, district_id=district_id,
                    authority_id=authority_id, language='en')
        user.set_password('pw')
        db.session.add(user)
        users[username] = user
    db.session.commit()
    keys = {'CAM-1': _device('CAM-1', a.id), 'ESP-1': _device('ESP-1', a.id, kind='sensor')}
    return {'a': a.id, 'b': b.id, 'u': {k: v.id for k, v in users.items()}, 'keys': keys}


def login(client, username):
    g.pop('_login_user', None)
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})
    g.pop('_login_user', None)


def jpeg(color=(30, 200, 30), size=(64, 48), exif=None):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG', **({'exif': exif} if exif is not None else {}))
    return buf.getvalue()


def iso(dt):
    return dt.replace(microsecond=0).isoformat() + 'Z'


def meta(**over):
    now = datetime.utcnow()
    data = {'client_event_id': str(uuid.uuid4()), 'captured_at': iso(now), 'latitude': NEAR[0],
            'longitude': NEAR[1], 'gps_accuracy_m': 8.5, 'gps_fix_at': iso(now), 'device_score': 0.93,
            'model': 'motion-gate', 'model_version': '0.1', 'app_version': '0.1.0', 'battery_pct': 81,
            'network_type': 'wifi'}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def post(client, world, metadata=None, frames=1, device='CAM-1', key=None, raw_metadata=None, extra=None,
         files=None):
    data = {'metadata': raw_metadata if raw_metadata is not None else json.dumps(metadata or meta())}
    if files is None:
        files = {f'frame_{i}': (io.BytesIO(jpeg()), f'frame_{i}.jpg', 'image/jpeg') for i in range(frames)}
    data.update(files)
    data.update(extra or {})
    headers = {'Authorization': f"Bearer {device}:{key or world['keys'][device]}"}
    return client.post('/api/iot/evidence', data=data, headers=headers, content_type='multipart/form-data')


def evidence(eid=None):
    db.session.expire_all()
    return db.session.get(NodeEvidence, eid) if eid else NodeEvidence.query.order_by(NodeEvidence.id.desc()).first()


# --- authentication -------------------------------------------------------------------------

class TestAuthentication:
    def test_valid_camera_node(self, client, world):
        r = post(client, world)
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert set(body) == {'success', 'duplicate', 'evidence_id', 'incident_id', 'status'}
        assert body['success'] is True and body['duplicate'] is False and body['status'] == 'attached'

    def test_x_device_headers_work_too(self, client, world):
        data = {'metadata': json.dumps(meta()), 'frame_0': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}
        r = client.post('/api/iot/evidence', data=data, content_type='multipart/form-data',
                        headers={'X-Device-ID': 'CAM-1', 'X-API-Key': world['keys']['CAM-1']})
        assert r.status_code == 201

    @pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer CAM-1:wrong-key'},
                                         {'Authorization': 'Bearer NOPE-1:whatever'}, {'Authorization': 'Bearer CAM-1'},
                                         {'Authorization': 'Basic CAM-1:x'}])
    def test_bad_credentials(self, client, world, headers):
        data = {'metadata': json.dumps(meta()), 'frame_0': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}
        r = client.post('/api/iot/evidence', data=data, headers=headers, content_type='multipart/form-data')
        assert r.status_code == 401
        assert NodeEvidence.query.count() == 0

    def test_disabled_device(self, client, world):
        IoTDevice.query.filter_by(device_id='CAM-1').update({'enabled': False})
        db.session.commit()
        assert post(client, world).status_code == 401

    def test_decommissioned_device_refused_even_if_enabled(self, client, world):
        IoTDevice.query.filter_by(device_id='CAM-1').update({'status': 'decommissioned', 'enabled': True})
        db.session.commit()
        assert post(client, world).status_code == 401
        # same rule on the telemetry endpoint (shared authenticate_device)
        r = client.post('/api/iot/telemetry', json={'readings': [{'sensor_type': 'battery', 'value': 50, 'unit': '%'}]},
                        headers={'Authorization': f"Bearer CAM-1:{world['keys']['CAM-1']}"})
        assert r.status_code == 401

    @pytest.mark.parametrize('status', ['active', 'inactive', 'maintenance'])
    def test_other_operator_statuses_still_authenticate(self, client, world, status):
        IoTDevice.query.filter_by(device_id='CAM-1').update({'status': status})
        db.session.commit()
        assert post(client, world).status_code == 201

    def test_rotated_key(self, client, world):
        cam = IoTDevice.query.filter_by(device_id='CAM-1').one()
        admin = db.session.get(User, world['u']['admin'])
        new_key, _ = admin_service.rotate_device_key(admin, cam)
        db.session.commit()
        assert post(client, world).status_code == 401  # old key
        assert post(client, world, key=new_key).status_code == 201

    def test_key_compared_in_constant_time(self, app, world, monkeypatch):
        import hmac
        calls = []
        real = hmac.compare_digest
        monkeypatch.setattr(hmac, 'compare_digest', lambda a, b: calls.append(1) or real(a, b))
        cam = IoTDevice.query.filter_by(device_id='CAM-1').one()
        assert cam.verify_api_key(world['keys']['CAM-1']) and not cam.verify_api_key('x')
        assert len(calls) == 2
        assert cam.api_key_hash == IoTDevice.hash_api_key(world['keys']['CAM-1'])  # still SHA-256 hash storage

    def test_sensor_device_cannot_upload_evidence(self, client, world):
        r = post(client, world, device='ESP-1')
        assert r.status_code == 403
        assert r.get_json() == {'error': 'This device is not a camera node'}
        assert NodeEvidence.query.count() == 0 and Incident.query.count() == 0

    def test_browser_session_is_not_device_auth(self, client, world):
        for who in ('admin', 'auth_a', 'citizen_a'):
            login(client, who)
            data = {'metadata': json.dumps(meta()), 'frame_0': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}
            assert client.post('/api/iot/evidence', data=data, content_type='multipart/form-data').status_code == 401

    def test_requires_multipart(self, client, world):
        r = client.post('/api/iot/evidence', json=meta(), headers={'Authorization': f"Bearer CAM-1:{world['keys']['CAM-1']}"})
        assert r.status_code == 400

    def test_csrf_exempt_for_device_but_enforced_for_review(self, app, client, world):
        app.config['WTF_CSRF_ENABLED'] = True
        r = post(client, world)
        assert r.status_code == 201
        login(client, 'admin')
        review = client.post(f"/api/iot/evidence/{r.get_json()['evidence_id']}/review", json={'status': 'accepted'})
        assert review.status_code == 400
        assert evidence().review_status == 'submitted'


# --- metadata --------------------------------------------------------------------------------

FORBIDDEN = ['severity', 'district', 'district_id', 'status', 'confirmed', 'authority', 'authority_id', 'recipients',
             'incident_id', 'event_type', 'hazard_type', 'source', 'received_at', 'affected_districts', 'device_id']


class TestMetadata:
    @pytest.mark.parametrize('field', FORBIDDEN)
    def test_each_server_owned_field_is_refused(self, client, world, field):
        r = post(client, world, meta(**{field: 'critical' if field != 'district_id' else world['b']}))
        assert r.status_code == 400
        assert 'Server-owned' in r.get_json()['error'] and field in r.get_json()['error']
        assert NodeEvidence.query.count() == 0 and Incident.query.count() == 0 and Notification.query.count() == 0

    def test_unknown_field_refused(self, client, world):
        r = post(client, world, meta(colour='green'))
        assert r.status_code == 400 and 'Unknown field' in r.get_json()['error']

    def test_unknown_form_field_refused(self, client, world):
        r = post(client, world, extra={'district_id': str(world['b'])})
        assert r.status_code == 400 and 'Unknown form field' in r.get_json()['error']

    @pytest.mark.parametrize('raw', ['', '{not json', '[1, 2]', '"text"', 'null', '{"a": 1' + ' ' * 5000 + '}'])
    def test_malformed_metadata(self, client, world, raw):
        assert post(client, world, raw_metadata=raw).status_code == 400

    def test_missing_metadata(self, client, world):
        data = {'frame_0': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}
        r = client.post('/api/iot/evidence', data=data, content_type='multipart/form-data',
                        headers={'Authorization': f"Bearer CAM-1:{world['keys']['CAM-1']}"})
        assert r.status_code == 400

    @pytest.mark.parametrize('value', [None, '', 'short', 'x' * 65, 'has space here', '../../etc/pa',
                                       12345678, True, 'üñíçødé-id'])
    def test_client_event_id(self, client, world, value):
        m = meta(client_event_id=value)
        if value is None:
            m.pop('client_event_id', None)
        assert post(client, world, m).status_code == 400

    @pytest.mark.parametrize('over', [
        {'latitude': 91, 'longitude': 85}, {'latitude': 27.7, 'longitude': 181}, {'longitude': None},
        {'latitude': None}, {'latitude': '27.7', 'longitude': '85.3'},
        {'latitude': True, 'longitude': 85.3}, {'gps_accuracy_m': -1}, {'gps_accuracy_m': 'good'},
        {'gps_accuracy_m': 1e9}, {'battery_pct': 101}, {'battery_pct': -1}, {'battery_pct': True},
        {'device_score': 1.5}, {'device_score': 'high'}, {'captured_at': 'yesterday'}, {'captured_at': 12},
        {'gps_fix_at': 'not-a-time'}, {'model': 'x' * 101}, {'model': ''}, {'app_version': 'v\n1'},
        {'network_type': 5}])
    def test_invalid_values(self, client, world, over):
        r = post(client, world, meta(**over))  # meta() drops None: latitude without longitude etc.
        assert r.status_code == 400, over
        assert NodeEvidence.query.count() == 0

    def test_nan_rejected(self, client, world):
        raw = json.dumps(meta()).replace('8.5', 'NaN')
        assert post(client, world, raw_metadata=raw).status_code == 400

    def test_missing_captured_at(self, client, world):
        m = meta()
        m.pop('captured_at')
        r = post(client, world, m)
        assert r.status_code == 400 and 'captured_at' in r.get_json()['error']

    def test_only_required_fields(self, client, world):
        r = post(client, world, {'client_event_id': 'evt-00000001', 'captured_at': iso(datetime.utcnow())})
        assert r.status_code == 201
        e = evidence()
        assert e.gps_status == 'missing' and e.location_source == 'registered'
        assert e.device_score is None and e.battery_pct is None


# --- server-owned context ----------------------------------------------------------------------

class TestServerOwnedContext:
    def test_incident_is_server_controlled(self, client, world):
        r = post(client, world, meta(device_score=1.0))
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        assert (incident.event_type, incident.severity, incident.source, incident.status) == \
            ('landslide', 'medium', 'iot', 'detected')
        assert incident.district_id == world['a']
        assert incident.source_reference == f"evidence_{r.get_json()['evidence_id']}"
        assert 'camera node CAM-1 node' in incident.title
        assert world['keys']['CAM-1'] not in json.dumps(incident.to_dict(include_internal=True))

    def test_gps_in_another_district_keeps_registered_district(self, client, world):
        r = post(client, world, meta(latitude=FAR[0], longitude=FAR[1]))
        assert r.status_code == 201
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        e = evidence()
        assert incident.district_id == world['a'] and incident.affected_district_ids == [world['a']]
        assert (incident.latitude, incident.longitude) == SITE  # registered location, not the phone's
        assert (e.latitude, e.longitude) == FAR and e.gps_status == 'outside_radius'
        assert e.location_source == 'registered' and e.district_id == world['a']

    def test_never_escalates_existing_event(self, client, world):
        first = post(client, world).get_json()
        Incident.query.update({'severity': 'high'})
        db.session.commit()
        post(client, world, meta(device_score=1.0))
        incident = db.session.get(Incident, first['incident_id'])
        db.session.refresh(incident)
        assert incident.severity == 'high' and incident.report_count == 2 and incident.status == 'detected'


# --- frames -----------------------------------------------------------------------------------

class TestFrames:
    def test_one_and_three_frames(self, client, world, dirs):
        post(client, world, frames=1)
        assert len(evidence().frames) == 1
        post(client, world, frames=3)
        e = evidence()
        assert len(e.frames) == 3 and all(STORED.match(n) for n in e.frames) and len(set(e.frames)) == 3
        assert sorted(os.listdir(dirs)) == sorted(evidence(1).frames + e.frames)

    def test_more_than_three_frames(self, client, world, dirs):
        files = {f'frame_{i}': (io.BytesIO(jpeg()), f'f{i}.jpg', 'image/jpeg') for i in range(4)}
        r = post(client, world, files=files)
        assert r.status_code == 400 and 'frame_3' in r.get_json()['error']
        assert NodeEvidence.query.count() == 0 and not os.path.exists(dirs)

    def test_no_frames_gap_or_repeat(self, client, world):
        assert post(client, world, files={}).status_code == 400
        assert post(client, world, files={'frame_1': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}).status_code == 400
        gap = {'frame_0': (io.BytesIO(jpeg()), 'a.jpg', 'image/jpeg'), 'frame_2': (io.BytesIO(jpeg()), 'b.jpg', 'image/jpeg')}
        assert post(client, world, files=gap).status_code == 400
        twice = {'frame_0': [(io.BytesIO(jpeg()), 'a.jpg', 'image/jpeg'), (io.BytesIO(jpeg()), 'b.jpg', 'image/jpeg')]}
        assert post(client, world, files=twice).status_code == 400
        assert NodeEvidence.query.count() == 0

    @pytest.mark.parametrize('payload, name, mimetype', [
        (b'not an image', 'f.jpg', 'image/jpeg'),
        (b'\xff\xd8\xff\xe0' + b'\x00' * 50, 'f.jpg', 'image/jpeg'),  # truncated JPEG
        (b'<svg onload=alert(1)>', 'f.svg', 'image/svg+xml'),
        (b'MZ\x90\x00', 'f.exe', 'application/octet-stream'),
    ])
    def test_invalid_or_malformed_images(self, client, world, dirs, payload, name, mimetype):
        r = post(client, world, files={'frame_0': (io.BytesIO(payload), name, mimetype)})
        assert r.status_code == 400 and r.get_json()['error'].startswith('frame_0:')
        assert NodeEvidence.query.count() == 0

    def test_png_content_with_jpg_name_refused(self, client, world):
        buf = io.BytesIO()
        Image.new('RGB', (8, 8)).save(buf, format='PNG')
        assert post(client, world, files={'frame_0': (io.BytesIO(buf.getvalue()), 'f.jpg', 'image/jpeg')}).status_code == 400

    def test_one_bad_frame_stores_nothing(self, client, world, dirs):
        files = {'frame_0': (io.BytesIO(jpeg()), 'a.jpg', 'image/jpeg'),
                 'frame_1': (io.BytesIO(b'junk'), 'b.jpg', 'image/jpeg')}
        assert post(client, world, files=files).status_code == 400
        assert NodeEvidence.query.count() == 0 and not os.path.exists(dirs)

    def test_exif_gps_stripped_and_reencoded(self, client, world, dirs):
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'
        exif[0x8825] = {1: 'N', 2: (27.0, 42.0, 0.0)}
        raw = jpeg(size=(3000, 2000), exif=exif.tobytes())
        assert b'PhoneMaker' in raw
        r = post(client, world, files={'frame_0': (io.BytesIO(raw), '../../../../evil name.jpg', 'image/jpeg')})
        assert r.status_code == 201
        name = evidence().frames[0]
        assert STORED.match(name) and 'evil' not in name
        with open(os.path.join(dirs, name), 'rb') as f:
            stored = f.read()
        assert b'PhoneMaker' not in stored and stored != raw
        with Image.open(io.BytesIO(stored)) as img:
            assert img.format == 'JPEG' and len(img.getexif()) == 0
            assert max(img.size) <= citizen_report_service.MAX_STORED_SIDE

    def test_decompression_bomb(self, client, world):
        buf = io.BytesIO()
        Image.new('1', (12000, 12000)).save(buf, format='PNG')
        assert post(client, world, files={'frame_0': (io.BytesIO(buf.getvalue()), 'f.png', 'image/png')}).status_code == 400

    def test_oversized_payload(self, app, client, world):
        app.config['MAX_CONTENT_LENGTH'] = 4096
        big = {'frame_0': (io.BytesIO(os.urandom(20000)), 'f.jpg', 'image/jpeg')}
        r = post(client, world, files=big)
        assert r.status_code == 413
        assert NodeEvidence.query.count() == 0


# --- idempotency / dedup ------------------------------------------------------------------------

class TestIdempotency:
    def test_same_event_twice(self, client, world, dirs):
        m = meta()
        first = post(client, world, m)
        notes = Notification.query.count()
        files = sorted(os.listdir(dirs))
        second = post(client, world, m, frames=3)
        assert first.status_code == 201 and second.status_code == 200
        a, b = first.get_json(), second.get_json()
        assert b['duplicate'] is True and b['success'] is True
        assert (b['evidence_id'], b['incident_id'], b['status']) == (a['evidence_id'], a['incident_id'], a['status'])
        assert NodeEvidence.query.count() == 1 and Incident.query.count() == 1
        assert Notification.query.count() == notes and sorted(os.listdir(dirs)) == files
        assert db.session.get(Incident, a['incident_id']).report_count == 1

    def test_same_client_id_on_another_device_is_independent(self, client, world):
        world['keys']['CAM-2'] = _device('CAM-2', world['a'])
        m = meta()
        assert post(client, world, m).status_code == 201
        assert post(client, world, m, device='CAM-2').status_code == 201
        assert NodeEvidence.query.count() == 2

    def test_different_events_merge_into_existing_incident(self, client, world):
        notes = None
        ids = set()
        for _ in range(3):
            ids.add(post(client, world).get_json()['incident_id'])
            notes = notes if notes is not None else Notification.query.count()
        assert len(ids) == 1 and Incident.query.count() == 1
        incident = db.session.get(Incident, ids.pop())
        assert incident.report_count == 3 and incident.severity == 'medium'
        assert Notification.query.count() == notes  # the 'detected' alert went out once

    def test_merges_into_citizen_landslide(self, app, client, world):
        login(client, 'citizen_a')
        client.post('/api/reports', content_type='multipart/form-data', data={
            'hazard_type': 'landslide', 'district_id': str(world['a']), 'latitude': str(NEAR[0]),
            'longitude': str(NEAR[1]), 'image': (io.BytesIO(jpeg()), 'p.jpg', 'image/jpeg')})
        citizen_incident = Incident.query.one()
        r = post(client, world)
        assert r.get_json()['incident_id'] == citizen_incident.id and Incident.query.count() == 1


# --- capture time -------------------------------------------------------------------------------

class TestTimestamps:
    def test_recent_capture_sets_detected_at(self, client, world):
        captured = datetime.utcnow().replace(microsecond=0) - timedelta(hours=2)
        r = post(client, world, meta(captured_at=iso(captured), gps_fix_at=iso(captured)))
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        e = evidence()
        assert incident.detected_at == captured and e.captured_at == captured
        assert e.received_at > captured and (datetime.utcnow() - e.received_at).total_seconds() < 60

    def test_offset_timestamp_normalized_to_utc(self, client, world):
        local = (datetime.utcnow() + timedelta(hours=5, minutes=45)).replace(microsecond=0)
        r = post(client, world, meta(captured_at=local.isoformat() + '+05:45', gps_fix_at=None))
        assert r.status_code == 201 and evidence().status == 'attached'

    def test_future_capture_is_held(self, client, world):
        future = datetime.utcnow() + timedelta(minutes=10)
        r = post(client, world, meta(captured_at=iso(future), gps_fix_at=iso(future)))
        assert r.status_code == 201
        body = r.get_json()
        assert body['status'] == 'held' and body['incident_id'] is None
        assert evidence().hold_reason == 'future_capture' and Incident.query.count() == 0
        assert Notification.query.count() == 0

    def test_small_clock_skew_accepted(self, client, world):
        soon = datetime.utcnow() + timedelta(minutes=2)
        assert post(client, world, meta(captured_at=iso(soon), gps_fix_at=iso(soon))).get_json()['status'] == 'attached'

    def test_stale_capture_is_held(self, client, world):
        old = datetime.utcnow() - timedelta(hours=73)
        r = post(client, world, meta(captured_at=iso(old), gps_fix_at=iso(old)))
        assert r.status_code == 201 and r.get_json()['status'] == 'held'
        assert evidence().hold_reason == 'stale_capture' and Incident.query.count() == 0

    def test_stale_gps_fix_falls_back(self, client, world):
        now = datetime.utcnow()
        r = post(client, world, meta(gps_fix_at=iso(now - timedelta(hours=1))))
        e = evidence()
        assert e.gps_status == 'stale_fix' and e.location_source == 'registered'
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        assert (incident.latitude, incident.longitude) == SITE


# --- GPS ----------------------------------------------------------------------------------------

class TestGps:
    def test_accepted_gps_used_for_incident(self, client, world):
        r = post(client, world)
        e = evidence()
        assert (e.gps_status, e.location_source) == ('accepted', 'gps')
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        assert (incident.latitude, incident.longitude) == NEAR

    @pytest.mark.parametrize('over, status', [
        ({'gps_accuracy_m': 500}, 'inaccurate'), ({'gps_accuracy_m': None}, 'inaccurate'),
        ({'latitude': None, 'longitude': None}, 'missing'),
        ({'latitude': FAR[0], 'longitude': FAR[1]}, 'outside_radius')])
    def test_bad_gps_recorded_and_registered_location_used(self, client, world, over, status):
        r = post(client, world, meta(**over))
        e = evidence()
        assert (e.gps_status, e.location_source) == (status, 'registered')
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        assert (incident.latitude, incident.longitude) == SITE and incident.district_id == world['a']

    def test_thresholds_are_configurable(self, app, client, world):
        app.config['NODE_MAX_DISTANCE_KM'] = 30
        post(client, world, meta(latitude=FAR[0], longitude=FAR[1]))
        assert evidence().gps_status == 'accepted'
        app.config['NODE_MAX_GPS_ACCURACY_M'] = 5
        post(client, world)
        assert evidence().gps_status == 'inaccurate'

    def test_node_without_registered_location(self, client, world):
        world['keys']['CAM-X'] = _device('CAM-X', world['a'], coords=None)
        r = post(client, world, device='CAM-X')
        e = evidence()
        assert (e.gps_status, e.location_source) == ('no_reference', 'district')
        assert (e.latitude, e.longitude) == NEAR  # recorded, but not trusted
        incident = db.session.get(Incident, r.get_json()['incident_id'])
        assert incident.latitude is None and incident.district_id == world['a']


# --- hold after rejection -------------------------------------------------------------------------

class TestHoldAfterRejection:
    def _reject(self, world, incident_id):
        incident = db.session.get(Incident, incident_id)
        hazard_event_service.reject_event(incident, 'false alarm: tree in wind', actor_id=world['u']['admin'])

    def test_hold_window_then_resume(self, app, client, world):
        first = post(client, world).get_json()
        self._reject(world, first['incident_id'])
        held = post(client, world)
        assert held.status_code == 201 and held.get_json()['status'] == 'held'
        assert evidence().hold_reason == 'after_rejection' and Incident.query.count() == 1
        # after NODE_HOLD_AFTER_REJECTION_HOURS normal processing resumes
        IncidentStatusHistory.query.update({'created_at': datetime.utcnow() - timedelta(hours=25)})
        db.session.commit()
        resumed = post(client, world).get_json()
        assert resumed['status'] == 'attached' and resumed['incident_id'] != first['incident_id']
        assert NodeEvidence.query.count() == 3  # nothing deleted

    def test_hold_does_not_block_attaching_to_active_event(self, client, world):
        first = post(client, world).get_json()
        self._reject(world, first['incident_id'])
        active = hazard_event_service.create_hazard_event('landslide', 'medium', 'authority', district_id=world['a'],
                                                          latitude=SITE[0], longitude=SITE[1])
        r = post(client, world).get_json()
        assert r['status'] == 'attached' and r['incident_id'] == active.id

    def test_rejection_of_other_device_does_not_hold(self, client, world):
        world['keys']['CAM-2'] = _device('CAM-2', world['a'])
        first = post(client, world, device='CAM-2').get_json()
        self._reject(world, first['incident_id'])
        assert post(client, world).get_json()['status'] == 'attached'


# --- rate limit -----------------------------------------------------------------------------------

class TestRateLimit:
    def test_limit(self, app, client, world):
        app.config['NODE_MAX_EVIDENCE_PER_HOUR'] = 2
        m = meta()
        assert post(client, world, m).status_code == 201
        assert post(client, world).status_code == 201
        r = post(client, world)
        assert r.status_code == 429 and 'retry later' in r.get_json()['error']
        assert NodeEvidence.query.count() == 2
        assert post(client, world, m).status_code == 200  # a retry of a stored event is not refused
        NodeEvidence.query.update({'received_at': datetime.utcnow() - timedelta(minutes=61)})
        db.session.commit()
        assert post(client, world).status_code == 201

    def test_limit_is_per_device(self, app, client, world):
        app.config['NODE_MAX_EVIDENCE_PER_HOUR'] = 1
        world['keys']['CAM-2'] = _device('CAM-2', world['a'])
        assert post(client, world).status_code == 201
        assert post(client, world).status_code == 429
        assert post(client, world, device='CAM-2').status_code == 201

    def test_concurrent_requests_cannot_bypass_limit(self, monkeypatch, tmp_path):
        """Real threads against a file-backed SQLite DB (the in-memory test DB is one connection)."""
        monkeypatch.setattr(TestingConfig, 'SQLALCHEMY_DATABASE_URI', f"sqlite:///{tmp_path / 'race.db'}")
        app = create_app('testing')
        app.config.update(NODE_MAX_EVIDENCE_PER_HOUR=2, EVIDENCE_UPLOAD_DIR=str(tmp_path / 'ev'))
        with app.app_context():
            db.create_all()
            district = District(name='Race', province='P')
            db.session.add(district)
            db.session.commit()
            key = _device('CAM-R', district.id)
            db.session.remove()
        workers, barrier, codes = 6, threading.Barrier(6), []

        def upload():
            client = app.test_client()
            data = {'metadata': json.dumps(meta()), 'frame_0': (io.BytesIO(jpeg()), 'f.jpg', 'image/jpeg')}
            barrier.wait()
            r = client.post('/api/iot/evidence', data=data, content_type='multipart/form-data',
                            headers={'Authorization': f'Bearer CAM-R:{key}'})
            codes.append(r.status_code)

        threads = [threading.Thread(target=upload) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with app.app_context():
            stored = NodeEvidence.query.count()
            incidents = Incident.query.count()
            db.session.remove()
            db.drop_all()
        assert sorted(codes) == [201, 201, 429, 429, 429, 429], codes
        assert stored == 2 and incidents == 1


# --- AI corroboration ----------------------------------------------------------------------------

class Stub:
    def __init__(self, fail=False):
        self.fail, self.seen = fail, []

    def scores(self, image):
        if self.fail:
            raise RuntimeError('boom')
        self.seen.append(image.getpixel((0, 0)))
        return {'road_damage': 0.05, 'landslide': 0.85, 'other': 0.10}


class TestAi:
    def test_ai_runs_on_last_frame(self, app, client, world, monkeypatch):
        stub = Stub()
        monkeypatch.setattr(vision_service, '_classifier', stub)
        app.config['VISION_ENABLED'] = True
        files = {'frame_0': (io.BytesIO(jpeg((200, 0, 0))), 'a.jpg', 'image/jpeg'),
                 'frame_1': (io.BytesIO(jpeg((0, 0, 200))), 'b.jpg', 'image/jpeg'),
                 'frame_2': (io.BytesIO(jpeg((255, 255, 255))), 'c.jpg', 'image/jpeg')}
        r = post(client, world, files=files)
        e = evidence()
        assert r.status_code == 201 and len(stub.seen) == 1 and min(stub.seen[0]) > 240  # the white post-event frame
        assert (e.ai_status, e.ai_label, e.ai_confidence) == ('completed', 'landslide', 0.85)
        incident = db.session.get(Incident, e.incident_id)
        assert incident.severity == 'medium' and incident.status == 'detected'  # AI never escalates

    def test_ai_failure_keeps_evidence(self, app, client, world, monkeypatch):
        monkeypatch.setattr(vision_service, '_classifier', Stub(fail=True))
        app.config['VISION_ENABLED'] = True
        r = post(client, world)
        e = evidence()
        assert r.status_code == 201 and e.status == 'attached' and e.ai_status == 'failed' and e.incident_id

    def test_ai_crash_after_commit_is_not_a_500(self, app, client, world, monkeypatch):
        app.config['VISION_ENABLED'] = True

        def crash(*a, **k):
            raise RuntimeError('db gone')
        monkeypatch.setattr(citizen_report_service, 'record_vision_analysis', crash)
        r = post(client, world)
        assert r.status_code == 201
        e = evidence()
        assert e.status == 'attached' and e.ai_status == 'not_analyzed' and Incident.query.count() == 1

    def test_ai_disabled(self, client, world):
        post(client, world)
        assert evidence().ai_status == 'not_analyzed'


# --- risk -------------------------------------------------------------------------------------------

class TestRisk:
    def test_field_node_is_a_distinct_source(self, client, world):
        r = post(client, world).get_json()
        post(client, world)
        [a] = risk_service.assess_incident(db.session.get(Incident, r['incident_id']))
        assert a.level == 'field_node_only' and a.sources == ['field_node']
        assert a.evidence['distinct_reporters'] == 0 and a.evidence['field_node_evidence'] == 2
        assert a.evidence['distinct_field_nodes'] == 1 and a.action == 'none' and a.severity is None

    def test_citizen_grades_unchanged_by_node_evidence(self, client, world):
        login(client, 'citizen_a')
        client.post('/api/reports', content_type='multipart/form-data', data={
            'hazard_type': 'landslide', 'district_id': str(world['a']), 'latitude': str(SITE[0]),
            'longitude': str(SITE[1]), 'image': (io.BytesIO(jpeg()), 'p.jpg', 'image/jpeg')})
        for _ in range(3):
            post(client, world)
        [a] = risk_service.assess_incident(Incident.query.one())
        assert a.level == 'single_report'  # nodes are not reporters: no 'supported'/'corroborated' inflation
        assert a.evidence['distinct_reporters'] == 1 and a.evidence['field_node_evidence'] == 3
        assert a.sources == ['citizen_report', 'field_node']

    def test_rejected_or_held_evidence_excluded(self, client, world):
        r = post(client, world).get_json()
        e = evidence(r['evidence_id'])
        e.review_status = 'rejected'
        db.session.commit()
        [a] = risk_service.assess_incident(db.session.get(Incident, r['incident_id']))
        assert a.level == 'insufficient' and 'field_node' not in a.sources


# --- notifications --------------------------------------------------------------------------------

class TestNotifications:
    @pytest.fixture
    def pushes(self, app, world, monkeypatch):
        app.config.update(VAPID_PUBLIC_KEY='pub', VAPID_PRIVATE_KEY='priv')
        sent = []
        monkeypatch.setattr(emergency_dispatcher, '_send', lambda sub, payload: sent.append((sub.user_id, payload)) or True)
        for i, name in enumerate(('citizen_a', 'citizen_b')):
            user = db.session.get(User, world['u'][name])
            user.emergency_alert_state = 'granted'
            db.session.add(PushSubscription(user_id=user.id, endpoint=f'https://fcm.googleapis.com/fcm/send/{i}',
                                            p256dh_key='k', auth_key='a'))
        db.session.commit()
        return sent

    def recipients(self, ntype='hazard_detected'):
        return {n.user_id for n in Notification.query.filter_by(type=ntype)}

    def test_registered_district_notified_not_others(self, client, world, pushes):
        post(client, world, meta(latitude=FAR[0], longitude=FAR[1]))  # GPS points elsewhere
        u = world['u']
        assert self.recipients() == {u['citizen_a'], u['auth_a'], u['admin']}
        assert pushes == []  # medium is below EMERGENCY_MIN_SEVERITY: no emergency push

    def test_authority_escalation_uses_existing_emergency_path(self, client, world, pushes):
        incident_id = post(client, world).get_json()['incident_id']
        login(client, 'auth_a')
        r = client.patch(f'/api/hazards/{incident_id}', json={'severity': 'high'})
        assert r.status_code == 200
        assert {uid for uid, _ in pushes} == {world['u']['citizen_a']}
        assert all(p['emergency'] for _, p in pushes)
        assert world['u']['citizen_b'] not in self.recipients('hazard_escalated')

    def test_other_district_authority_cannot_escalate(self, client, world, pushes):
        incident_id = post(client, world).get_json()['incident_id']
        login(client, 'auth_b')
        assert client.patch(f'/api/hazards/{incident_id}', json={'severity': 'critical'}).status_code == 403
        assert pushes == []


# --- frames: authorization --------------------------------------------------------------------------

class TestFrameAccess:
    @pytest.fixture
    def eid(self, client, world):
        return post(client, world, frames=2).get_json()['evidence_id']

    @pytest.mark.parametrize('who', ['admin', 'auth_a'])
    def test_authorized(self, client, world, eid, who):
        login(client, who)
        r = client.get(f'/api/iot/evidence/{eid}/frames/1')
        assert r.status_code == 200 and r.mimetype == 'image/jpeg'
        assert r.headers['Cache-Control'] == 'private, no-store'
        assert 'evidence' not in r.headers.get('Content-Disposition', '').lower().replace('inline', '')

    @pytest.mark.parametrize('who', ['auth_b', 'citizen_a', 'citizen_b'])
    def test_refused_as_not_found(self, client, world, eid, who):
        login(client, who)
        assert client.get(f'/api/iot/evidence/{eid}/frames/0').status_code == 404
        assert client.get('/api/iot/evidence/9999/frames/0').status_code == 404

    def test_logged_out(self, client, world, eid):
        client.get('/auth/logout')
        assert client.get(f'/api/iot/evidence/{eid}/frames/0').status_code == 401

    def test_device_credentials_cannot_read_frames(self, client, world, eid):
        r = client.get(f'/api/iot/evidence/{eid}/frames/0',
                       headers={'Authorization': f"Bearer CAM-1:{world['keys']['CAM-1']}"})
        assert r.status_code == 401

    @pytest.mark.parametrize('path', ['frames/2', 'frames/-1', 'frames/..%2f..%2fapp.py', 'frames/0/../../x'])
    def test_bad_index_and_traversal(self, client, world, eid, path):
        login(client, 'admin')
        assert client.get(f'/api/iot/evidence/{eid}/{path}').status_code == 404

    def test_tampered_stored_name_not_read(self, client, world, eid):
        e = evidence(eid)
        e.frame_filenames = '../../config.py,' + e.frames[1]
        db.session.commit()
        login(client, 'admin')
        r = client.get(f'/api/iot/evidence/{eid}/frames/0')
        assert r.status_code == 404 and b'SECRET' not in r.data and 'config' not in r.get_data(as_text=True)

    def test_review_rules(self, client, world, eid):
        login(client, 'auth_b')
        assert client.post(f'/api/iot/evidence/{eid}/review', json={'status': 'rejected'}).status_code == 404
        login(client, 'citizen_a')
        assert client.post(f'/api/iot/evidence/{eid}/review', json={'status': 'rejected'}).status_code == 404
        login(client, 'auth_a')
        assert client.post(f'/api/iot/evidence/{eid}/review', json={'status': 'maybe'}).status_code == 400
        r = client.post(f'/api/iot/evidence/{eid}/review', json={'status': 'accepted', 'severity': 'critical'})
        assert r.status_code == 200 and r.get_json()['evidence']['review_status'] == 'accepted'
        assert client.post(f'/api/iot/evidence/{eid}/review', json={'status': 'rejected'}).status_code == 409
        incident = db.session.get(Incident, evidence(eid).incident_id)
        assert (incident.status, incident.severity) == ('detected', 'medium')  # review never touches the hazard


# --- battery heartbeat ------------------------------------------------------------------------------

class TestBatteryTelemetry:
    def telemetry(self, client, world, device, readings):
        return client.post('/api/iot/telemetry', json={'readings': readings},
                           headers={'Authorization': f"Bearer {device}:{world['keys'][device]}"})

    def test_camera_node_battery_heartbeat(self, client, world):
        r = self.telemetry(client, world, 'CAM-1', [{'sensor_type': 'battery', 'value': 64, 'unit': '%'}])
        assert r.status_code == 201
        assert SensorReading.query.one().sensor_type == 'battery' and Incident.query.count() == 0
        assert IoTDevice.query.filter_by(device_id='CAM-1').one().last_seen is not None

    @pytest.mark.parametrize('reading', [{'sensor_type': 'battery', 'value': 101, 'unit': '%'},
                                         {'sensor_type': 'battery', 'value': 50, 'unit': 'V'}])
    def test_invalid_battery(self, client, world, reading):
        assert self.telemetry(client, world, 'CAM-1', [reading]).status_code == 400

    @pytest.mark.parametrize('reading', [{'sensor_type': 'water_level', 'value': 9.0, 'unit': 'm'},
                                         {'sensor_type': 'vibration', 'value': 900, 'unit': 'mg'}])
    def test_camera_node_cannot_drive_hazard_rules(self, client, world, reading):
        r = self.telemetry(client, world, 'CAM-1', [reading])
        assert r.status_code == 400 and 'camera nodes may only send battery' in json.dumps(r.get_json())
        assert SensorReading.query.count() == 0 and Incident.query.count() == 0

    def test_sensor_may_send_battery_but_need_not(self, client, world):
        assert self.telemetry(client, world, 'ESP-1', [{'sensor_type': 'battery', 'value': 90, 'unit': '%'}]).status_code == 201


# --- secrets / XSS -----------------------------------------------------------------------------------

class TestSecrets:
    def test_api_key_never_leaks(self, app, client, world, caplog, dirs):
        key = world['keys']['CAM-1']
        caplog.set_level(logging.DEBUG)
        app.config['VISION_ENABLED'] = True  # model missing in tests -> logged failure path runs too
        app.config['VISION_MODEL_PATH'] = str(dirs / 'no-model')
        r = post(client, world)
        body = r.get_data(as_text=True)
        assert key not in body and IoTDevice.hash_api_key(key) not in body and str(dirs) not in body
        assert key not in caplog.text and IoTDevice.hash_api_key(key) not in caplog.text
        dump = '\n'.join(db.engine.raw_connection().driver_connection.iterdump())
        assert key not in dump and IoTDevice.hash_api_key(key) in dump  # only the hash is stored
        login(client, 'admin')
        page = client.get(f"/admin/devices/{IoTDevice.query.filter_by(device_id='CAM-1').one().id}").get_data(as_text=True)
        assert key not in page and IoTDevice.hash_api_key(key) not in page

    def test_metadata_is_escaped_in_reviewer_pages(self, client, world):
        xss = '<script>alert(1)</script>'
        assert post(client, world, meta(model=xss, app_version='"><img src=x>')).status_code == 201
        login(client, 'admin')
        for url in ('/reports/review', f"/admin/devices/{IoTDevice.query.filter_by(device_id='CAM-1').one().id}"):
            html = client.get(url).get_data(as_text=True)
            assert xss not in html and '"><img src=x>' not in html
        assert '&lt;script&gt;' in client.get('/reports/review').get_data(as_text=True)


# --- reviewer UI ---------------------------------------------------------------------------------------

class TestReviewPage:
    def test_district_scoping(self, client, world):
        post(client, world, meta(battery_pct=55))
        login(client, 'auth_a')
        html = client.get('/reports/review').get_data(as_text=True)
        assert 'Source: field node' in html and 'CAM-1 node' in html and '/api/iot/evidence/1/frames/0' in html
        assert 'accepted' in html and '55%' in html  # GPS validation state + battery
        login(client, 'auth_b')
        assert 'CAM-1 node' not in client.get('/reports/review').get_data(as_text=True)
        login(client, 'citizen_a')
        assert client.get('/reports/review').status_code == 403


# --- Super Admin provisioning ----------------------------------------------------------------------------

def register_form(world, **over):
    data = {'device_id': 'PHONE-NODE-01', 'name': 'Highway slope phone', 'district_id': world['a'],
            'kind': 'camera_node', 'latitude': '27.7', 'longitude': '85.3',
            'location_description': 'Slope at km 42', 'reason': 'M-LIVE-02 field node'}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


class TestProvisioning:
    def test_register_camera_node(self, client, world):
        login(client, 'admin')
        page = client.get('/admin/devices/new').get_data(as_text=True)
        assert 'Camera node' in page and 'trusted identity for field evidence uploads' in page
        r = client.post('/admin/devices/new', data=register_form(world))
        assert r.status_code == 302
        device = IoTDevice.query.filter_by(device_id='PHONE-NODE-01').one()
        assert device.kind == 'camera_node' and device.river_id is None and device.district_id == world['a']
        key = re.search(r'class="secret-once".*?<code>([A-Za-z0-9_-]{40,})</code>',
                        client.get(r.headers['Location']).get_data(as_text=True), re.S).group(1)
        assert key not in client.get(r.headers['Location']).get_data(as_text=True)  # shown once
        audit = AuditLog.query.filter_by(action='REGISTERED_DEVICE', success=True).one()
        assert 'kind camera_node' in audit.summary and key not in audit.summary
        world['keys']['PHONE-NODE-01'] = key
        assert post(client, world, device='PHONE-NODE-01').status_code == 201

    @pytest.mark.parametrize('over, message', [({'kind': None}, 'Choose the device kind'),
                                                ({'kind': 'drone'}, 'Choose the device kind'),
                                                ({'kind': 'sensor'}, 'Choose what the device monitors')])
    def test_kind_must_be_explicit(self, client, world, over, message):
        login(client, 'admin')
        r = client.post('/admin/devices/new', data=register_form(world, **over))
        assert r.status_code == 400 and message in r.get_data(as_text=True)
        assert IoTDevice.query.filter_by(device_id='PHONE-NODE-01').count() == 0
        assert AuditLog.query.filter_by(action='REGISTERED_DEVICE', success=False).count() == 1

    def test_camera_node_has_no_river(self, client, world):
        from app.models import River
        river = River(name='R', district_id=world['a'], danger_level=3)
        db.session.add(river)
        db.session.commit()
        login(client, 'admin')
        r = client.post('/admin/devices/new', data=register_form(world, river_id=str(river.id)))
        assert r.status_code == 400 and 'does not monitor a river' in r.get_data(as_text=True)

    def test_kind_cannot_be_changed_by_edit(self, client, world):
        login(client, 'admin')
        cam = IoTDevice.query.filter_by(device_id='CAM-1').one()
        client.post(f'/admin/devices/{cam.id}/edit', data={'status': 'maintenance', 'kind': 'sensor',
                                                           'reason': 'try to convert'})
        db.session.expire_all()
        cam = IoTDevice.query.filter_by(device_id='CAM-1').one()
        assert cam.status == 'maintenance' and cam.kind == 'camera_node'

    def test_kind_cannot_be_changed_by_patch_api(self, client, world):
        login(client, 'admin')
        esp = IoTDevice.query.filter_by(device_id='ESP-1').one()
        r = client.patch(f'/api/iot/devices/{esp.id}', json={'kind': 'camera_node'})
        assert r.status_code == 400 and 'kind' in r.get_json()['error']
        db.session.expire_all()
        assert db.session.get(IoTDevice, esp.id).kind == 'sensor'

    def test_json_api_registration_is_always_sensor(self, client, world):
        login(client, 'admin')
        r = client.post('/api/iot/devices', json={'device_id': 'API-1', 'name': 'x', 'district_id': world['a'],
                                                  'kind': 'camera_node'})
        assert r.status_code == 201 and r.get_json()['device']['kind'] == 'sensor'

    @pytest.mark.parametrize('who', ['auth_a', 'citizen_a'])
    def test_non_admin_cannot_provision(self, client, world, who):
        login(client, who)
        assert client.post('/admin/devices/new', data=register_form(world)).status_code == 403
        assert IoTDevice.query.filter_by(device_id='PHONE-NODE-01').count() == 0

    def test_existing_devices_default_to_sensor(self, app):
        district = District(name='D', province='P')
        db.session.add(district)
        db.session.commit()
        device = IoTDevice(device_id='OLD-1', name='old', district_id=district.id, api_key_hash='x')
        db.session.add(device)
        db.session.commit()
        assert device.kind == 'sensor'

    def test_device_detail_shows_evidence(self, client, world):
        post(client, world)
        login(client, 'admin')
        cam = IoTDevice.query.filter_by(device_id='CAM-1').one()
        html = client.get(f'/admin/devices/{cam.id}').get_data(as_text=True)
        assert 'Field evidence' in html and 'Camera node' in html and f'/api/iot/evidence/1/frames/0' in html
        assert 'attached' in html and 'accepted' in html
