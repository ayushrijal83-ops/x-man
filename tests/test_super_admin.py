"""Super Admin Control Center: authorization, IoT control, authority/citizen deactivation, hazard and
report intervention, Web Push management, append-only audit log, session termination, secret
protection, CSRF/XSS/IDOR, and the migration."""
import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import pytest
from flask import g
from PIL import Image

from app import create_app
from app.extensions import RUNTIME, db
from app.models import (AuditLog, Authority, CitizenReport, District, Incident, IncidentStatusHistory, IoTDevice,
                        Notification, PushSubscription, SensorReading, User)
from app.services import web_push
from app.services.hazard_event_service import create_hazard_event

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC, PRIVATE = web_push.generate_vapid_keys()
READING = {'readings': [{'sensor_type': 'water_level', 'value': 1.5, 'unit': 'm'}]}


@pytest.fixture(autouse=True)
def no_real_push(monkeypatch):
    class Response:
        status_code = 201
    monkeypatch.setattr(web_push.requests, 'post', lambda *a, **k: Response())


@pytest.fixture
def app():
    app = create_app('testing')
    app.config.update(VAPID_PUBLIC_KEY=PUBLIC, VAPID_PRIVATE_KEY=PRIVATE)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def world(app):
    a, b = District(name='Alpha', province='Bagmati'), District(name='Beta', province='Koshi')
    db.session.add_all([a, b])
    db.session.commit()
    auth_a = Authority(name='Alpha Office', category='disaster', district_id=a.id)
    auth_b = Authority(name='Beta Office', category='roads', district_id=b.id)
    auth_x = Authority(name='Unlinked Office', category='water', district_id=b.id)
    db.session.add_all([auth_a, auth_b, auth_x])
    db.session.commit()
    ids = {}
    for name, role, district, authority in [('cit_a', 'citizen', a, None), ('cit_b', 'citizen', b, None),
                                            ('auth_a', 'authority', a, auth_a), ('auth_b', 'authority', b, auth_b),
                                            ('root', 'admin', None, None), ('root2', 'admin', None, None)]:
        user = User(username=name, email=f'{name}@t.np', role=role, district_id=district.id if district else None,
                    authority_id=authority.id if authority else None, language='en')
        user.set_password('original-pw')
        db.session.add(user)
        db.session.flush()
        ids[name] = user.id
    devices = {}
    for device_id, district, authority in [('ESP32-FLOOD-001', a, auth_a), ('ESP32-MOTION-002', b, auth_b)]:
        device = IoTDevice(device_id=device_id, name=f'{district.name} node', district_id=district.id,
                           authority_id=authority.id, firmware_version='1.0.0',
                           api_key_hash=IoTDevice.hash_api_key(f'key-{device_id}'))
        db.session.add(device)
        db.session.flush()
        devices[device_id] = device.id
    db.session.commit()
    return {'a': a.id, 'b': b.id, 'auth_a': auth_a.id, 'auth_b': auth_b.id, 'auth_x': auth_x.id, 'u': ids,
            'dev': devices}


def login(client, username, password='original-pw'):
    g.pop('_login_user', None)  # several test clients share one app context
    client.get('/auth/logout')
    client.get('/language/set/en')
    path = '/auth/login' if username.startswith('cit') else '/auth/authority/login'
    response = client.post(path, data={'username': username, 'password': password})
    g.pop('_login_user', None)
    return response


def as_client(client, method, url, **kw):
    g.pop('_login_user', None)
    response = client.open(url, method=method, **kw)
    g.pop('_login_user', None)
    return response


def text(response):
    body = response.get_data(as_text=True)
    response.close()
    return body


def telemetry(client, device_id, key=None):
    return client.post('/api/iot/telemetry', json=READING,
                       headers={'Authorization': f"Bearer {device_id}:{key or 'key-' + device_id}"})


def audit(action):
    return AuditLog.query.filter_by(action=action).order_by(AuditLog.id.desc()).all()


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (32, 24), (90, 90, 90)).save(buf, format='JPEG')
    return buf.getvalue()


GETS = ['/admin', '/admin/users', '/admin/citizens', '/admin/authorities', '/admin/devices', '/admin/devices/status.json',
        '/admin/hazards', '/admin/reports', '/admin/notifications', '/admin/push', '/admin/audit', '/admin/health']


# ============================================================================ authorization

class TestAuthorization:
    def test_super_admin_reaches_every_page(self, client, world):
        hazard = create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
        login(client, 'root')
        for url in GETS + [f"/admin/devices/{world['dev']['ESP32-FLOOD-001']}", f'/admin/hazards/{hazard.id}',
                           f"/admin/citizens/{world['u']['cit_a']}", f"/admin/authorities/{world['auth_a']}"]:
            assert client.get(url).status_code == 200, url

    @pytest.mark.parametrize('who', ['cit_a', 'auth_a'])
    def test_citizen_and_authority_denied_every_rule_and_method(self, app, client, world, who):
        """Direct URL and direct POST: every /admin rule, whatever it is, answers 403."""
        login(client, who)
        rules = [r for r in app.url_map.iter_rules() if r.rule.startswith('/admin')]
        assert len(rules) >= 25
        for rule in rules:
            url = re.sub(r'<int:\w+>', '1', rule.rule)
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                assert client.open(url, method=method, data={'reason': 'x', 'confirm': 'DISABLE DEVICE',
                                                             'enabled': '0', 'active': '0'}).status_code == 403, url
        assert db.session.get(IoTDevice, world['dev']['ESP32-FLOOD-001']).enabled
        assert all(u.is_active for u in User.query) and AuditLog.query.count() == 0

    def test_anonymous_is_sent_to_login_and_json_poll_is_not_public(self, client, world):
        for url in ('/admin/devices', '/admin/devices/status.json', '/admin/audit'):
            response = client.get(url)
            assert response.status_code == 302 and '/auth/login' in response.headers['Location']
        response = client.post(f"/admin/devices/{world['dev']['ESP32-FLOOD-001']}/status",
                               data={'enabled': '0', 'reason': 'x', 'confirm': 'DISABLE DEVICE'})
        assert response.status_code == 302 and db.session.get(IoTDevice, world['dev']['ESP32-FLOOD-001']).enabled

    def test_admin_accounts_are_not_manageable_idor(self, client, world):
        """No 'normal admin' tier exists: admin == Super Admin, and no admin can act on another admin
        (or on themselves) through the user endpoints."""
        login(client, 'root')
        for target in ('root', 'root2'):
            uid = world['u'][target]
            for action, data in [('status', {'active': '0', 'reason': 'x', 'confirm': 'DISABLE ACCOUNT'}),
                                 ('reset-password', {'temporary_password': 'Temp-Pass-1', 'confirm_password': 'Temp-Pass-1',
                                                     'reason': 'x'}),
                                 ('force-password-change', {'reason': 'x'}), ('end-sessions', {'reason': 'x'})]:
                assert client.post(f'/admin/users/{uid}/{action}', data=data).status_code == 404
        root2 = db.session.get(User, world['u']['root2'])
        assert root2.is_active and root2.check_password('original-pw') and not root2.must_change_password
        for url in ('/admin/devices/9999', '/admin/hazards/9999', '/admin/authorities/9999', '/admin/citizens/9999'):
            assert client.get(url).status_code == 404
        for url in ('/admin/devices/9999/status', '/admin/devices/9999/rotate-key', '/admin/hazards/9999/status',
                    '/admin/reports/9999/review', '/admin/push/9999/disable', '/admin/authorities/9999/status'):
            assert client.post(url, data={'reason': 'x', 'status': 'accepted', 'enabled': '1', 'active': '1'}).status_code == 404

    def test_no_broadcast_endpoint_exists(self, app):
        """Emergency notifications come only from hazard events, never from an admin button."""
        rules = [r.rule for r in app.url_map.iter_rules() if r.rule.startswith('/admin')]
        assert not any(word in rule for rule in rules for word in ('broadcast', 'send', 'notify'))
        assert not any('POST' in r.methods for r in app.url_map.iter_rules() if r.rule.startswith('/admin/notifications'))


# ============================================================================ IoT

class TestIotControl:
    def test_list_filter_search_and_derived_status(self, client, world):
        dev = db.session.get(IoTDevice, world['dev']['ESP32-FLOOD-001'])
        dev.last_seen = datetime.utcnow() - timedelta(minutes=2)
        other = db.session.get(IoTDevice, world['dev']['ESP32-MOTION-002'])
        other.last_seen = datetime.utcnow() - timedelta(hours=3)
        db.session.add(SensorReading(device_id=dev.id, sensor_type='water_level', value=1.0, unit='m'))
        db.session.commit()
        login(client, 'root')
        page = text(client.get('/admin/devices'))
        assert 'ESP32-FLOOD-001' in page and 'ESP32-MOTION-002' in page and 'Offline — no telemetry received recently' in page
        page = text(client.get(f"/admin/devices?district_id={world['b']}"))
        assert 'ESP32-MOTION-002' in page and 'ESP32-FLOOD-001' not in page
        page = text(client.get('/admin/devices?q=flood'))
        assert 'ESP32-FLOOD-001' in page and 'ESP32-MOTION-002' not in page
        page = text(client.get('/admin/devices?status=online'))
        assert 'ESP32-FLOOD-001' in page and 'ESP32-MOTION-002' not in page
        page = text(client.get('/admin/devices?status=offline'))
        assert 'ESP32-MOTION-002' in page and 'ESP32-FLOOD-001' not in page
        page = text(client.get('/admin/devices?sensor_type=water_level'))
        assert 'ESP32-FLOOD-001' in page and 'ESP32-MOTION-002' not in page
        assert client.get('/admin/devices?status=<x>&sensor_type=nope&page=-1').status_code == 200
        states = client.get('/admin/devices/status.json').get_json()['states']
        assert states == {str(dev.id): 'online', str(other.id): 'offline'}
        # viewing never rewrites the stored operator status
        assert db.session.get(IoTDevice, other.id).status == 'active'

    def test_disable_requires_reason_and_typed_confirmation(self, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        for data in ({'enabled': '0'}, {'enabled': '0', 'reason': 'maintenance'},
                     {'enabled': '0', 'reason': 'maintenance', 'confirm': 'disable device'},
                     {'enabled': '0', 'reason': '   ', 'confirm': 'DISABLE DEVICE'},
                     {'enabled': '0', 'reason': 'x' * 501, 'confirm': 'DISABLE DEVICE'}):
            client.post(f'/admin/devices/{pk}/status', data=data)
            assert db.session.get(IoTDevice, pk).enabled
        assert client.post(f'/admin/devices/{pk}/status', data={'enabled': 'yes', 'reason': 'x'}).status_code == 400
        assert AuditLog.query.count() == 0

    def test_disconnect_and_connect_control_telemetry(self, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        device_client = client.application.test_client()
        assert telemetry(device_client, 'ESP32-FLOOD-001').status_code == 201
        login(client, 'root')
        response = client.post(f'/admin/devices/{pk}/status', follow_redirects=True,
                               data={'enabled': '0', 'reason': 'maintenance', 'confirm': 'DISABLE DEVICE'})
        page = text(response)
        assert 'Device disabled by Super Admin.' in page and 'maintenance' in page
        assert 'may still be powered and on Wi-Fi' in page  # never claims a physical disconnect
        assert telemetry(device_client, 'ESP32-FLOOD-001').status_code == 401
        entry = audit('DISABLED_DEVICE')[0]
        assert (entry.actor_username, entry.actor_role, entry.target_type, entry.target_id, entry.target_label,
                entry.reason, entry.success) == ('root', 'admin', 'device', str(pk), 'ESP32-FLOOD-001', 'maintenance', True)
        assert client.get('/admin/devices/status.json').get_json()['states'][str(pk)] == 'disabled'

        client.post(f'/admin/devices/{pk}/status', data={'enabled': '1', 'reason': 'maintenance done'})
        assert telemetry(device_client, 'ESP32-FLOOD-001').status_code == 201
        assert audit('ENABLED_DEVICE')[0].reason == 'maintenance done'
        # repeating an action that changes nothing is refused and audited as a failure
        client.post(f'/admin/devices/{pk}/status', data={'enabled': '1', 'reason': 'again'})
        assert audit('ENABLED_DEVICE')[0].success is False

    def test_device_pages_never_show_key_hashes(self, client, world):
        login(client, 'root')
        hashes = [d.api_key_hash for d in IoTDevice.query]
        for url in GETS + [f'/admin/devices/{pk}' for pk in world['dev'].values()]:
            body = text(client.get(url))
            assert not any(h in body for h in hashes) and 'key-ESP32' not in body, url

    def test_telemetry_history_filters_and_pagination(self, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        now = datetime.utcnow()
        for i in range(60):
            db.session.add(SensorReading(device_id=pk, sensor_type='water_level', value=i, unit='m',
                                         received_at=now - timedelta(minutes=i), recorded_at=now - timedelta(minutes=i)))
        db.session.add(SensorReading(device_id=pk, sensor_type='temperature', value=21.5, unit='°C',
                                     received_at=now - timedelta(days=3), recorded_at=now - timedelta(days=3)))
        db.session.commit()
        login(client, 'root')
        page = text(client.get(f'/admin/devices/{pk}'))
        assert 'Telemetry history' in page and '· 61' in page and 'Page 1 / 2' in page
        next_link = page.split('rel="next" href="')[1].split('"')[0]
        assert 'page=2' in next_link and f'/admin/devices/{pk}' in next_link
        assert '· 1</h2>' in text(client.get(f'/admin/devices/{pk}?sensor_type=temperature'))
        page = text(client.get(f'/admin/devices/{pk}?hours=24'))
        assert '· 60' in page and '<td>21.5</td>' not in page  # history rows: value and unit in separate cells
        assert '· 61' in text(client.get(f'/admin/devices/{pk}?hours=7'))  # unsupported window = all time

    def test_authority_device_patch_still_works_and_is_scoped(self, client, world):
        """The existing authority device API is untouched by the Super Admin layer."""
        login(client, 'auth_a')
        own, other = world['dev']['ESP32-FLOOD-001'], world['dev']['ESP32-MOTION-002']
        assert client.patch(f'/api/iot/devices/{own}', json={'enabled': False}).status_code == 200
        assert client.patch(f'/api/iot/devices/{other}', json={'enabled': False}).status_code == 403


def shown_key(page):
    """The plaintext key from the one-time box, or None."""
    match = re.search(r'class="secret-once".*?<code>([A-Za-z0-9_-]{40,})</code>', page, re.S)
    return match.group(1) if match else None


class TestKeyRotation:
    """Post/Redirect/Get: only an explicit, confirmed POST rotates; the key is shown once on the
    redirected GET; reloads, revisits and back/forward are plain GETs and change nothing."""
    OLD = 'key-ESP32-FLOOD-001'

    def _rotate(self, client, pk, **data):
        return client.post(f'/admin/devices/{pk}/rotate-key',
                           data={'reason': 'credential leak', 'confirm': 'ROTATE KEY', **data})

    def _hash(self, pk):
        db.session.expire_all()
        return db.session.get(IoTDevice, pk).api_key_hash

    def test_get_never_rotates(self, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        before = self._hash(pk)
        for _ in range(5):  # open, refresh, revisit, with filters
            assert client.get(f'/admin/devices/{pk}').status_code == 200
            assert client.get(f'/admin/devices/{pk}?hours=24&page=2').status_code == 200
        assert client.get(f'/admin/devices/{pk}/rotate-key').status_code == 405
        assert self._hash(pk) == before and AuditLog.query.count() == 0

    def test_rotation_is_post_redirect_get_and_shown_once(self, app, client, world, caplog):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        before = self._hash(pk)
        with caplog.at_level('DEBUG'):
            response = self._rotate(client, pk)
            # the POST answers with a redirect, not with the key
            assert response.status_code == 302 and response.headers['Location'].endswith(f'/admin/devices/{pk}')
            assert shown_key(text(response)) is None
            after = self._hash(pk)
            assert after != before
            # the cookie holds only an opaque lookup token, never the key
            with client.session_transaction() as s:
                pending = s['one_time_key']
            assert pending.startswith(f'{pk}:')

            first = client.get(f'/admin/devices/{pk}')
            assert first.headers['Cache-Control'] == 'no-store'
            page = text(first)
            key = shown_key(page)
            assert key and IoTDevice.hash_api_key(key) == after and 'Shown only once' in page
            assert key not in pending and key not in response.headers['Location']
            # never inside a script block (no path into localStorage/sessionStorage)
            assert not any(key in block for block in re.findall(r'<script.*?</script>', page, re.S))

            # refresh, navigate away and back, reopen: no key shown, no rotation
            for url in (f'/admin/devices/{pk}', '/admin/devices', '/admin', f'/admin/devices/{pk}',
                        f'/admin/devices/{pk}'):
                assert key not in text(client.get(url)), url
            assert self._hash(pk) == after
            with client.session_transaction() as s:
                assert 'one_time_key' not in s
            assert all(key not in c.value for c in client._cookies.values())
        assert not any(key in r.getMessage() for r in caplog.records)
        assert len(audit('ROTATED_DEVICE_KEY')) == 1

        device_client = app.test_client()
        assert telemetry(device_client, 'ESP32-FLOOD-001', self.OLD).status_code == 401
        assert telemetry(device_client, 'ESP32-FLOOD-001', key).status_code == 201
        # still valid later; only another explicit rotation changes it
        client.get(f'/admin/devices/{pk}')
        assert telemetry(device_client, 'ESP32-FLOOD-001', key).status_code == 201

    def test_plaintext_key_is_not_persisted(self, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        self._rotate(client, pk)
        key = shown_key(text(client.get(f'/admin/devices/{pk}')))
        dump = '\n'.join(db.session.connection().connection.driver_connection.iterdump())
        assert key and key not in dump and IoTDevice.hash_api_key(key) in dump

    def test_second_explicit_rotation_invalidates_first_key(self, app, client, world):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        self._rotate(client, pk)
        first = shown_key(text(client.get(f'/admin/devices/{pk}')))
        self._rotate(client, pk, reason='second leak')
        second = shown_key(text(client.get(f'/admin/devices/{pk}')))
        assert first and second and first != second
        device_client = app.test_client()
        assert telemetry(device_client, 'ESP32-FLOOD-001', first).status_code == 401
        assert telemetry(device_client, 'ESP32-FLOOD-001', second).status_code == 201

    @pytest.mark.parametrize('data', [{'reason': ''}, {'reason': '   '}, {'confirm': ''}, {'confirm': 'rotate key'},
                                      {'confirm': 'ROTATE'}, {'reason': 'x' * 501}])
    def test_missing_reason_or_wrong_phrase_rejected(self, app, client, world, data):
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        before = self._hash(pk)
        assert self._rotate(client, pk, **data).status_code == 302
        assert shown_key(text(client.get(f'/admin/devices/{pk}'))) is None and self._hash(pk) == before
        assert telemetry(app.test_client(), 'ESP32-FLOOD-001', self.OLD).status_code == 201
        with client.session_transaction() as s:
            assert 'one_time_key' not in s

    @pytest.mark.parametrize('who', ['cit_a', 'auth_a', None])
    def test_unauthorized_cannot_rotate(self, client, world, who):
        pk = world['dev']['ESP32-FLOOD-001']
        before = self._hash(pk)
        if who:
            login(client, who)
            assert self._rotate(client, pk).status_code == 403
        else:
            assert '/auth/login' in self._rotate(client, pk).headers['Location']
        assert self._hash(pk) == before

    def test_key_is_bound_to_the_rotating_admin_and_device(self, app, client, world):
        pk, other = world['dev']['ESP32-FLOOD-001'], world['dev']['ESP32-MOTION-002']
        login(client, 'root')
        self._rotate(client, pk)
        with client.session_transaction() as s:
            token = s['one_time_key'].partition(':')[2]
        # another admin replaying the token gets nothing (and the token is spent)
        second = app.test_client()
        login(second, 'root2')
        with second.session_transaction() as s:
            s['one_time_key'] = f'{pk}:{token}'
        assert shown_key(text(as_client(second, 'GET', f'/admin/devices/{pk}'))) is None
        assert shown_key(text(client.get(f'/admin/devices/{pk}'))) is None
        assert shown_key(text(client.get(f'/admin/devices/{other}'))) is None

    def test_wrong_device_page_does_not_consume_the_key(self, client, world):
        pk, other = world['dev']['ESP32-FLOOD-001'], world['dev']['ESP32-MOTION-002']
        login(client, 'root')
        self._rotate(client, pk)
        assert shown_key(text(client.get(f'/admin/devices/{other}'))) is None
        assert shown_key(text(client.get(f'/admin/devices/{pk}')))

    def test_one_time_key_expires(self, client, world, monkeypatch):
        from app.services import admin_service
        pk = world['dev']['ESP32-FLOOD-001']
        login(client, 'root')
        self._rotate(client, pk)
        real = admin_service.time.monotonic
        monkeypatch.setattr(admin_service.time, 'monotonic', lambda: real() + admin_service.ONE_TIME_KEY_SECONDS + 1)
        assert shown_key(text(client.get(f'/admin/devices/{pk}'))) is None


# ============================================================================ authorities

class TestAuthorities:
    def test_deactivate_authority_preserves_history_and_ends_sessions(self, client, world):
        hazard = create_hazard_event('landslide', 'high', 'authority', district_id=world['a'])
        authority_client = client.application.test_client()
        login(authority_client, 'auth_a')
        assert as_client(authority_client, 'GET', '/authority/dashboard').status_code == 200

        login(client, 'root')
        page = text(client.get(f"/admin/authorities/{world['auth_a']}"))
        assert 'Historical hazards, citizen reports and response records are preserved.' in page
        assert 'DISABLE AUTHORITY' in page
        client.post(f"/admin/authorities/{world['auth_a']}/status", data={'active': '0', 'reason': 'x', 'confirm': 'DISABLE'})
        assert db.session.get(User, world['u']['auth_a']).is_active
        client.post(f"/admin/authorities/{world['auth_a']}/status",
                    data={'active': '0', 'reason': 'Authority account no longer responsible for district.',
                          'confirm': 'DISABLE AUTHORITY'})
        assert db.session.get(User, world['u']['auth_a']).is_active is False
        assert as_client(authority_client, 'GET', '/authority/dashboard').status_code == 302  # session ended
        # nothing deleted, nothing else touched
        assert db.session.get(Authority, world['auth_a']) and db.session.get(Incident, hazard.id)
        assert db.session.get(IoTDevice, world['dev']['ESP32-FLOOD-001']).enabled
        assert db.session.get(User, world['u']['auth_b']).is_active
        entry = audit('DISABLED_AUTHORITY')[0]
        assert entry.target_label == 'Authority: Alpha Office' and 'responsible' in entry.reason and entry.success
        assert '@auth_a' in entry.summary
        assert len(audit('DISABLED_AUTHORITY')) == 1  # the bad typed phrase never reached the action
        page = text(client.get('/admin/authorities?status=disabled'))
        assert 'Alpha Office' in page

        client.post(f"/admin/authorities/{world['auth_a']}/status", data={'active': '1', 'reason': 'back on duty'})
        assert db.session.get(User, world['u']['auth_a']).is_active
        login(authority_client, 'auth_a')
        assert as_client(authority_client, 'GET', '/authority/dashboard').status_code == 200

    def test_deactivating_unlinked_authority_is_refused_and_audited(self, client, world):
        login(client, 'root')
        client.post(f"/admin/authorities/{world['auth_x']}/status",
                    data={'active': '0', 'reason': 'cleanup', 'confirm': 'DISABLE AUTHORITY'})
        entry = audit('DISABLED_AUTHORITY')[0]
        assert entry.success is False and 'No account is linked' in entry.summary

    def test_authority_password_reset_and_force_change_audited(self, client, world):
        uid = world['u']['auth_a']
        login(client, 'root')
        client.post(f'/admin/users/{uid}/reset-password', data={'temporary_password': 'Temp-Pass-123',
                                                               'confirm_password': 'Temp-Pass-123'})
        assert db.session.get(User, uid).check_password('original-pw')  # no reason -> nothing happens
        client.post(f'/admin/users/{uid}/reset-password', data={'temporary_password': 'Temp-Pass-123',
                                                               'confirm_password': 'Temp-Pass-123',
                                                               'reason': 'administrative password reset'})
        user = db.session.get(User, uid)
        assert user.check_password('Temp-Pass-123') and user.must_change_password
        entry = audit('RESET_PASSWORD')[0]
        assert entry.target_label == 'User: @auth_a (authority)' and entry.reason == 'administrative password reset'
        for value in (entry.summary, entry.reason, entry.target_label):
            assert 'Temp-Pass-123' not in value and user.password_hash not in value

    def test_authority_list_search_filter(self, client, world):
        login(client, 'root')
        assert 'Beta Office' in text(client.get('/admin/authorities?q=beta'))
        page = text(client.get(f"/admin/authorities?district_id={world['b']}"))
        assert 'Beta Office' in page and 'Unlinked Office' in page and 'Alpha Office' not in page


# ============================================================================ citizens

class TestCitizens:
    def test_directory_columns(self, client, world):
        login(client, 'cit_a')  # sets last_login_at
        login(client, 'root')
        page = text(client.get('/admin/citizens'))
        assert 'Last login' in page and 'Reports' in page and '@cit_a' in page and '@auth_a' not in page
        page = text(client.get(f"/admin/citizens?district_id={world['b']}&q=cit"))
        assert '@cit_b' in page and '@cit_a' not in page

    def test_deactivate_and_reactivate_without_reviving_old_sessions(self, client, world):
        uid = world['u']['cit_a']
        citizen = client.application.test_client()
        login(citizen, 'cit_a')
        assert as_client(citizen, 'GET', '/dashboard').status_code == 200
        login(client, 'root')
        client.post(f'/admin/users/{uid}/status', data={'active': '0', 'reason': 'abuse', 'confirm': 'DISABLE ACCOUNT'})
        assert db.session.get(User, uid).is_active is False
        assert as_client(citizen, 'GET', '/dashboard').status_code == 302
        client.post(f'/admin/users/{uid}/status', data={'active': '1', 'reason': 'appeal accepted'})
        assert db.session.get(User, uid).is_active
        # the session that existed before the disable must not come back to life
        assert as_client(citizen, 'GET', '/dashboard').status_code == 302
        assert [e.action for e in AuditLog.query.order_by(AuditLog.id)] == ['DISABLED_USER', 'ENABLED_USER']
        page = text(client.get(f'/admin/citizens/{uid}'))
        assert 'abuse' in page and 'appeal accepted' in page  # account history on the detail page

    def test_end_sessions_keeps_account_usable(self, client, world):
        uid = world['u']['cit_a']
        citizen = client.application.test_client()
        login(citizen, 'cit_a')
        login(client, 'root')
        client.post(f'/admin/users/{uid}/end-sessions', data={'reason': 'lost phone'})
        assert as_client(citizen, 'GET', '/dashboard').status_code == 302
        assert db.session.get(User, uid).is_active and audit('TERMINATED_SESSIONS')[0].success
        login(citizen, 'cit_a')
        assert as_client(citizen, 'GET', '/dashboard').status_code == 200

    def test_force_password_change_and_reset(self, client, world):
        uid = world['u']['cit_b']
        login(client, 'root')
        client.post(f'/admin/users/{uid}/force-password-change', data={'reason': 'weak password'})
        assert db.session.get(User, uid).must_change_password
        response = login(client.application.test_client(), 'cit_b')
        assert response.status_code == 302 and '/profile/change-password' in response.headers['Location']
        client.post(f'/admin/users/{uid}/reset-password', data={'temporary_password': 'Citizen-Temp-9',
                                                               'confirm_password': 'Citizen-Temp-9', 'reason': 'locked out'})
        assert db.session.get(User, uid).check_password('Citizen-Temp-9')
        assert [e.action for e in AuditLog.query.order_by(AuditLog.id)] == ['FORCED_PASSWORD_CHANGE', 'RESET_PASSWORD']

    def test_detail_shows_own_reports_only(self, app, client, world, tmp_path):
        app.config['REPORT_UPLOAD_DIR'] = str(tmp_path)
        for who, district in (('cit_a', world['a']), ('cit_b', world['b'])):
            login(client, who)
            assert client.post('/api/reports', data={
                'hazard_type': 'landslide', 'district_id': str(district), 'description': f'secret note of {who}',
                'image': (io.BytesIO(_jpeg()), 'p.jpg', 'image/jpeg')}).status_code == 201
        login(client, 'root')
        page = text(client.get(f"/admin/citizens/{world['u']['cit_a']}"))
        mine = CitizenReport.query.filter_by(reporter_id=world['u']['cit_a']).one()
        theirs = CitizenReport.query.filter_by(reporter_id=world['u']['cit_b']).one()
        assert f'#{mine.id} ' in page and f'#{theirs.id} ' not in page and 'Submitted reports · 1' in page


# ============================================================================ hazards

class TestHazards:
    def test_sees_all_districts_and_filters(self, client, world):
        create_hazard_event('flood', 'critical', 'authority', district_id=world['a'], title='Alpha flood')
        create_hazard_event('landslide', 'low', 'authority', district_id=world['b'], title='Beta slide')
        login(client, 'root')
        page = text(client.get('/admin/hazards'))
        assert 'Alpha flood' in page and 'Beta slide' in page
        assert 'Beta slide' not in text(client.get(f"/admin/hazards?district_id={world['a']}"))
        assert 'Alpha flood' not in text(client.get('/admin/hazards?event_type=landslide'))
        assert 'Beta slide' not in text(client.get('/admin/hazards?severity=critical'))
        assert 'Alpha flood' in text(client.get('/admin/hazards?status=active'))
        assert 'Alpha flood' not in text(client.get('/admin/hazards?status=resolved'))

    def test_intervention_follows_lifecycle_and_is_audited(self, client, world):
        hazard = create_hazard_event('flood', 'high', 'authority', district_id=world['a'], title='River')
        login(client, 'root')
        url = f'/admin/hazards/{hazard.id}/status'
        client.post(url, data={'status': 'investigating', 'reason': 'verify'})  # missing typed phrase
        assert db.session.get(Incident, hazard.id).status == 'detected'
        client.post(url, data={'status': 'resolved', 'reason': 'skip ahead', 'confirm': 'CHANGE HAZARD STATUS'})
        assert db.session.get(Incident, hazard.id).status == 'detected'
        refused = audit('CHANGED_HAZARD_STATUS')[0]
        assert refused.success is False and 'Invalid transition' in refused.summary

        notified = Notification.query.filter_by(incident_id=hazard.id).count()
        for step in ('investigating', 'confirmed'):
            client.post(url, data={'status': step, 'reason': f'field team says {step}', 'confirm': 'CHANGE HAZARD STATUS'})
        incident = db.session.get(Incident, hazard.id)
        assert incident.status == 'confirmed'
        history = IncidentStatusHistory.query.filter_by(incident_id=hazard.id).order_by(IncidentStatusHistory.id).all()
        assert [(h.new_status, h.changed_by_id) for h in history] == [('investigating', world['u']['root']),
                                                                       ('confirmed', world['u']['root'])]
        assert history[-1].note == 'Super Admin intervention: field team says confirmed'
        assert Notification.query.filter_by(incident_id=hazard.id).count() > notified  # normal confirmed alert
        ok = [e for e in audit('CHANGED_HAZARD_STATUS') if e.success]
        assert len(ok) == 2 and ok[0].summary == f'hazard #{hazard.id} status investigating -> confirmed'
        page = text(client.get(f'/admin/hazards/{hazard.id}'))
        assert 'field team says confirmed' in page and 'Move to response' in page and 'Move to detected' not in page

    def test_closed_hazard_offers_no_transitions(self, client, world):
        hazard = create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
        from app.services.hazard_event_service import reject_event
        reject_event(hazard, 'false alarm')
        login(client, 'root')
        assert 'lifecycle cannot change' in text(client.get(f'/admin/hazards/{hazard.id}'))
        client.post(f'/admin/hazards/{hazard.id}/status',
                    data={'status': 'detected', 'reason': 'reopen', 'confirm': 'CHANGE HAZARD STATUS'})
        assert db.session.get(Incident, hazard.id).status == 'rejected'


# ============================================================================ reports

class TestReports:
    @pytest.fixture
    def report(self, app, client, world, tmp_path):
        app.config['REPORT_UPLOAD_DIR'] = str(tmp_path)
        login(client, 'cit_a')
        assert client.post('/api/reports', data={
            'hazard_type': 'road_damage', 'district_id': str(world['a']), 'description': 'Crack near bridge',
            'image': (io.BytesIO(_jpeg()), 'p.jpg', 'image/jpeg')}).status_code == 201
        report = CitizenReport.query.one()
        report.ai_status, report.ai_label, report.ai_confidence = 'completed', 'landslide', 0.8
        db.session.commit()
        return report.id

    def test_view_filter_and_review(self, client, world, report):
        login(client, 'root')
        page = text(client.get('/admin/reports'))
        assert f'#{report} ' in page and '@cit_a' in page and 'Disagrees' in page
        assert f'#{report} ' in text(client.get('/admin/reports?ai=disagree'))
        assert f'#{report} ' not in text(client.get('/admin/reports?status=accepted'))
        client.post(f'/admin/reports/{report}/review', data={'status': 'accepted'})  # no reason
        assert db.session.get(CitizenReport, report).status == 'submitted'
        client.post(f'/admin/reports/{report}/review', data={'status': 'accepted', 'reason': 'clear photo'})
        rep = db.session.get(CitizenReport, report)
        assert rep.status == 'accepted' and rep.reviewed_by_id == world['u']['root']
        assert rep.description == 'Crack near bridge' and rep.hazard_type == 'road_damage'  # evidence untouched
        client.post(f'/admin/reports/{report}/review', data={'status': 'rejected', 'reason': 'changed my mind'})
        assert db.session.get(CitizenReport, report).status == 'accepted'
        assert [e.success for e in audit('REVIEWED_REPORT')] == [False, True]
        assert client.post(f'/admin/reports/{report}/review', data={'status': 'deleted', 'reason': 'x'}).status_code == 400

    def test_authority_cannot_use_admin_review(self, client, world, report):
        login(client, 'auth_a')
        assert client.post(f'/admin/reports/{report}/review', data={'status': 'rejected', 'reason': 'x'}).status_code == 403
        assert db.session.get(CitizenReport, report).status == 'submitted'


# ============================================================================ notifications / push

class TestNotificationsAndPush:
    def _subscription(self, uid, failures=0, enabled=True):
        sub = PushSubscription(user_id=uid, endpoint=f'https://fcm.googleapis.com/fcm/send/secret-{uid}-{failures}',
                               p256dh_key='BPUBLICKEYSECRETVALUE', auth_key='AUTHSECRETVALUE', user_agent='Chrome',
                               enabled=enabled, failure_count=failures)
        db.session.add(sub)
        db.session.commit()
        return sub.id

    def test_push_state_without_secrets_and_safe_disable(self, client, world):
        live = self._subscription(world['u']['cit_a'])
        failing = self._subscription(world['u']['cit_b'], failures=3)
        login(client, 'root')
        for url in ('/admin/push', '/admin/push?status=failing', '/admin/notifications', '/admin', '/admin/health'):
            page = text(client.get(url))
            assert 'secret-' not in page and 'SECRETVALUE' not in page and PRIVATE not in page, url
        page = text(client.get('/admin/push'))
        assert '@cit_a' in page and '@cit_b' in page and '3 consecutive failures' in page
        assert '@cit_a' not in text(client.get('/admin/push?status=failing'))
        client.post(f'/admin/push/{failing}/disable', data={'reason': 'dead endpoint'})
        assert db.session.get(PushSubscription, failing).enabled is False
        assert db.session.get(PushSubscription, live).enabled
        entry = audit('DISABLED_PUSH_SUBSCRIPTION')[0]
        assert entry.success and 'secret' not in entry.summary and 'SECRET' not in entry.summary

    def test_notification_page_shows_recipients_and_unread(self, client, world):
        create_hazard_event('flood', 'critical', 'authority', district_id=world['a'], title='Flood alert')
        login(client, 'root')
        page = text(client.get('/admin/notifications'))
        assert 'unread across all users' in page and 'Flood alert' in page and 'no broadcast button' in page
        hazard = Incident.query.one()
        page = text(client.get(f'/admin/hazards/{hazard.id}'))
        assert 'Notification state' in page and 'website alert' in page


# ============================================================================ audit log

class TestAuditLog:
    def test_append_only(self, app, world):
        root = db.session.get(User, world['u']['root'])
        from app.services import admin_service
        admin_service.record(root, 'DISABLED_DEVICE', 'device', 1, 'ESP32', 'maintenance', 'summary')
        db.session.commit()
        entry = AuditLog.query.one()
        entry.reason = 'rewritten'
        with pytest.raises(PermissionError):
            db.session.commit()
        db.session.rollback()
        with pytest.raises(PermissionError):
            db.session.delete(AuditLog.query.one())
            db.session.commit()
        db.session.rollback()
        assert AuditLog.query.one().reason == 'maintenance'

    def test_no_route_can_change_entries(self, app):
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/admin/audit'):
                assert rule.methods - {'HEAD', 'OPTIONS'} == {'GET'}

    def test_filters_and_escaping(self, client, world):
        login(client, 'root')
        client.post(f"/admin/users/{world['u']['cit_a']}/end-sessions", data={'reason': '<script>alert(1)</script>'})
        client.post(f"/admin/devices/{world['dev']['ESP32-FLOOD-001']}/status",
                    data={'enabled': '0', 'reason': 'maintenance', 'confirm': 'DISABLE DEVICE'})
        page = text(client.get('/admin/audit'))
        assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page
        page = text(client.get('/admin/audit?action=DISABLED_DEVICE'))
        assert 'ESP32-FLOOD-001' in page and '&lt;script&gt;' not in page
        assert 'ESP32-FLOOD-001' not in text(client.get('/admin/audit?target_type=user'))
        assert 'ESP32-FLOOD-001' in text(client.get('/admin/audit?q=maint'))
        assert 'ESP32-FLOOD-001' not in text(client.get('/admin/audit?outcome=failure'))

    def test_entries_never_contain_credentials(self, client, world):
        login(client, 'root')
        client.post(f"/admin/users/{world['u']['auth_b']}/reset-password",
                    data={'temporary_password': 'Super-Temp-77', 'confirm_password': 'Super-Temp-77', 'reason': 'r'})
        response = client.post(f"/admin/devices/{world['dev']['ESP32-MOTION-002']}/rotate-key",
                               data={'reason': 'r', 'confirm': 'ROTATE KEY'}, follow_redirects=True)
        key = shown_key(text(response))
        secrets = ['Super-Temp-77', key, db.session.get(User, world['u']['auth_b']).password_hash,
                   db.session.get(IoTDevice, world['dev']['ESP32-MOTION-002']).api_key_hash, PRIVATE,
                   client.application.config['SECRET_KEY']]
        for entry in AuditLog.query:
            row = ' '.join(str(getattr(entry, c.name)) for c in AuditLog.__table__.columns)
            assert not any(s in row for s in secrets)


# ============================================================================ security

class TestSecurity:
    def test_csrf_enforced_on_every_super_admin_post(self, world):
        app = create_app('testing')
        app.config.update(WTF_CSRF_ENABLED=True)
        with app.app_context():
            db.create_all()
            root = User(username='rootx', email='rootx@t.np', role='admin')
            root.set_password('pw')
            d = District(name='Z', province='P')
            db.session.add_all([root, d])
            db.session.commit()
            dev = IoTDevice(device_id='D1', name='n', district_id=d.id, api_key_hash='h')
            db.session.add(dev)
            db.session.commit()
            client = app.test_client()
            with client.session_transaction() as s:
                s['_user_id'] = root.get_id()
                s['_fresh'] = True
            for url in (f'/admin/devices/{dev.id}/status', f'/admin/devices/{dev.id}/rotate-key',
                        f'/admin/hazards/1/status', '/admin/authorities/1/status', '/admin/push/1/disable',
                        f'/admin/users/{root.id}/end-sessions', '/admin/reports/1/review'):
                assert client.post(url, data={'enabled': '0', 'reason': 'x', 'confirm': 'DISABLE DEVICE'}).status_code == 400, url
            assert db.session.get(IoTDevice, dev.id).enabled and db.session.get(IoTDevice, dev.id).api_key_hash == 'h'
            db.session.remove()
            db.drop_all()

    def test_session_identity_is_versioned(self, client, world):
        user = db.session.get(User, world['u']['cit_a'])
        assert user.get_id() == f'{user.id}:0'
        legacy = client.application.test_client()
        with legacy.session_transaction() as s:  # a session from before versioning (bare id) still works
            s['_user_id'] = str(user.id)
            s['_fresh'] = True
        assert as_client(legacy, 'GET', '/dashboard').status_code == 200
        for bad in (f'{user.id}:x', f'{user.id}:1', 'abc', f'{user.id}:-1'):
            forged = client.application.test_client()
            with forged.session_transaction() as s:
                s['_user_id'] = bad
            assert as_client(forged, 'GET', '/dashboard').status_code == 302, bad
        user.end_sessions()
        db.session.commit()
        assert as_client(legacy, 'GET', '/dashboard').status_code == 302

    def test_remember_me_cookie_is_revoked_too(self, client, world):
        citizen = client.application.test_client()
        g.pop('_login_user', None)
        citizen.post('/auth/login', data={'username': 'cit_a', 'password': 'original-pw', 'remember': 'on'})
        with citizen.session_transaction() as s:
            s.clear()  # browser restarted: only the remember-me cookie is left
        assert as_client(citizen, 'GET', '/dashboard').status_code == 200
        with citizen.session_transaction() as s:
            s.clear()
        db.session.get(User, world['u']['cit_a']).end_sessions()
        db.session.commit()
        assert as_client(citizen, 'GET', '/dashboard').status_code == 302

    def test_user_content_is_escaped_on_new_pages(self, client, world):
        device = db.session.get(IoTDevice, world['dev']['ESP32-FLOOD-001'])
        device.name = '<img src=x onerror=alert(1)>'
        create_hazard_event('flood', 'high', 'authority', district_id=world['a'], title='<script>alert(2)</script>')
        db.session.commit()
        login(client, 'root')
        hazard = Incident.query.one()
        for url in ('/admin/devices', f'/admin/devices/{device.id}', '/admin/hazards', f'/admin/hazards/{hazard.id}',
                    '/admin', '/admin/health'):
            page = text(client.get(url))
            assert '<img src=x' not in page and '<script>alert(2)' not in page, url

    def test_health_counts_rejections_without_secrets(self, client, world):
        before = RUNTIME['telemetry_rejected_auth'], RUNTIME['telemetry_rejected_invalid']
        assert telemetry(client, 'ESP32-FLOOD-001', 'wrong-key').status_code == 401
        assert client.post('/api/iot/telemetry', json={'readings': []},
                           headers={'Authorization': 'Bearer ESP32-FLOOD-001:key-ESP32-FLOOD-001'}).status_code == 400
        assert (RUNTIME['telemetry_rejected_auth'], RUNTIME['telemetry_rejected_invalid']) == (before[0] + 1, before[1] + 1)
        login(client, 'root')
        page = text(client.get('/admin/health'))
        app = client.application
        assert 'Telemetry refused' in page and PRIVATE not in page and app.config['SECRET_KEY'] not in page
        assert 'wrong-key' not in page


# ============================================================================ dashboard numbers

def test_dashboard_counts_come_from_the_database(client, world):
    db.session.get(User, world['u']['cit_b']).is_active = False
    db.session.get(IoTDevice, world['dev']['ESP32-MOTION-002']).enabled = False
    db.session.commit()
    create_hazard_event('flood', 'critical', 'authority', district_id=world['a'])
    create_hazard_event('landslide', 'medium', 'authority', district_id=world['b'])
    from app.services import admin_service
    o = admin_service.dashboard()
    assert o['users']['citizen'] == {'total': 2, 'active': 1, 'disabled': 1}
    assert o['users']['authority'] == {'total': 2, 'active': 2, 'disabled': 0}
    assert o['users']['admin']['total'] == 2
    assert (o['iot']['total'], o['iot']['enabled'], o['iot']['disabled'], o['iot']['states']['never']) == (2, 1, 1, 1)
    assert o['hazards']['active'] == 2 and o['hazards']['by_severity']['critical'] == 1
    assert dict(o['hazards']['by_district']) == {'Alpha': 1, 'Beta': 1}
    login(client, 'root')
    page = text(client.get('/admin'))
    assert 'Super Admin Control Center' in page and 'By sensor type' in page and 'System health' in page


# ============================================================================ migration

def test_migration_upgrade_downgrade_and_fresh_install(tmp_path):
    """Fresh install (init_db.py stamps the head), then down one step (M12) and up again; the models
    must match the migrations at every head (`flask db check`). The pre-M01 chain cannot build an empty
    database from scratch, which is why fresh installs use init_db.py (see test_security_m10)."""
    path = tmp_path / 'sa.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path.as_posix()}', 'FLASK_APP': 'run.py',
           'VISION_ENABLED': 'false', 'PYTHONIOENCODING': 'utf-8'}

    def run(*args):
        return subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)

    def schema():
        con = sqlite3.connect(path)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        users = {r[1] for r in con.execute('PRAGMA table_info(users)')}
        audit_columns = {r[1] for r in con.execute('PRAGMA table_info(audit_logs)')}
        con.close()
        return tables, users, audit_columns

    def current():
        result = run('-m', 'flask', 'db', 'current')
        return result.stdout + result.stderr

    assert run('init_db.py').returncode == 0
    assert 'e7413efdd252 (head)' in current()  # M-LIVE-02 is the head now; the SA revision is one below
    assert run('-m', 'flask', 'db', 'check').returncode == 0
    tables, users, audit_columns = schema()
    assert 'session_version' in users and {'actor_username', 'action', 'target_type', 'target_id', 'reason',
                                           'summary', 'success'} <= audit_columns

    result = run('-m', 'flask', 'db', 'downgrade', 'f3b8d2e6a417')
    assert result.returncode == 0, result.stderr[-800:]
    assert 'f3b8d2e6a417' in current()
    tables, users, _ = schema()
    assert 'audit_logs' not in tables and 'session_version' not in users and 'is_active' in users

    for step in (('upgrade',), ('check',)):
        result = run('-m', 'flask', 'db', *step)
        assert result.returncode == 0, (step, result.stderr[-800:])
    assert 'e7413efdd252 (head)' in current()
    tables, users, _ = schema()
    assert 'audit_logs' in tables and 'session_version' in users
