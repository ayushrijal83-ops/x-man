"""M12: admin control center, account status / forced password change, emergency alert preferences,
Web Push (RFC 8291/8292) and the three notification layers on top of M03/M04 hazard notifications."""
import json
import os
import re
import struct
import subprocess
import sys

import pytest
from flask import g
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import create_app
from app.extensions import db
from app.models import Authority, District, Incident, IoTDevice, Notification, PushSubscription, User
from app.services import emergency_dispatcher, hazard_event_service, notification_service, web_push
from app.services.hazard_event_service import create_hazard_event, report_hazard

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC, PRIVATE = web_push.generate_vapid_keys()


# ============================================================================ fixtures / helpers

class Browser:
    """A fake browser push subscription: real P-256 keys so payloads can be decrypted like a UA does."""

    def __init__(self, name):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.p256dh = web_push.b64url_encode(self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.auth = web_push.b64url_encode(os.urandom(16))
        self.endpoint = f'https://fcm.googleapis.com/fcm/send/{name}'

    def json(self):
        return {'subscription': {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}}

    def decrypt(self, body):
        """RFC 8291 receiver side."""
        salt, (rs, idlen) = body[:16], struct.unpack('!IB', body[16:21])
        as_public, ciphertext = body[21:21 + idlen], body[21 + idlen:]
        secret = self.key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
        ua_public = web_push.b64url_decode(self.p256dh)
        prk_key = web_push._hmac(web_push.b64url_decode(self.auth), secret)
        ikm = web_push._hmac(prk_key, b'WebPush: info\x00' + ua_public + as_public + b'\x01')
        prk = web_push._hmac(salt, ikm)
        cek = web_push._hmac(prk, b'Content-Encoding: aes128gcm\x00\x01')[:16]
        nonce = web_push._hmac(prk, b'Content-Encoding: nonce\x00\x01')[:12]
        plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
        assert plain.endswith(b'\x02') and rs == 4096
        return json.loads(plain[:-1])


class PushService:
    """Stands in for FCM/Mozilla: records every POST, answers with a configurable status."""

    def __init__(self):
        self.sent, self.status, self.raise_error = [], {}, None

    def post(self, endpoint, data, headers, timeout):
        if self.raise_error:
            raise self.raise_error
        self.sent.append({'endpoint': endpoint, 'body': data, 'headers': headers})

        class Response:
            status_code = self.status.get(endpoint, 201)
        return Response()

    def to(self, browser):
        return [browser.decrypt(s['body']) for s in self.sent if s['endpoint'] == browser.endpoint]


@pytest.fixture(autouse=True)
def push(monkeypatch):
    """Autouse: no test in this module ever reaches a real push service."""
    service = PushService()
    monkeypatch.setattr(web_push.requests, 'post', service.post)
    return service


@pytest.fixture
def app():
    app = create_app('testing')
    app.config.update(VAPID_PUBLIC_KEY=PUBLIC, VAPID_PRIVATE_KEY=PRIVATE, VAPID_SUBJECT='mailto:ops@x-man.test')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def world(app):
    with app.app_context():
        a, b, c = (District(name=n, province='Bagmati') for n in ('Alpha', 'Beta', 'Gamma'))
        db.session.add_all([a, b, c])
        db.session.commit()
        auth_a = Authority(name='Alpha Office', category='disaster', district_id=a.id)
        auth_b = Authority(name='Beta Office', category='roads', district_id=b.id)
        auth_c = Authority(name='Gamma Unlinked Office', category='water', district_id=c.id)
        db.session.add_all([auth_a, auth_b, auth_c])
        db.session.commit()
        users = {}
        for i, (name, role, district, authority) in enumerate([
                ('cit_a1', 'citizen', a, None), ('cit_a2', 'citizen', a, None), ('cit_b', 'citizen', b, None),
                ('cit_none', 'citizen', None, None), ('auth_a', 'authority', a, auth_a),
                ('auth_b', 'authority', b, auth_b), ('admin', 'admin', None, None)]):
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district.id if district else None,
                        authority_id=authority.id if authority else None, phone=f'+97798220000{i:02d}',
                        full_name=f'Full {name}', current_latitude=27.123456, current_longitude=85.654321,
                        language='en')  # pushes use the saved language; Nepali is covered in test_final_qa
            user.set_password('original-pw')
            db.session.add(user)
            users[name] = user
        db.session.add(IoTDevice(device_id='ESP32-FLOOD-001', name='Alpha gauge', district_id=a.id,
                                 authority_id=auth_a.id, api_key_hash=IoTDevice.hash_api_key('device-secret')))
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'c': c.id, 'auth_a': auth_a.id, 'auth_b': auth_b.id, 'auth_c': auth_c.id,
                'u': {k: v.id for k, v in users.items()}}


def login(client, username, password='original-pw'):
    client.get('/auth/logout')
    client.get('/language/set/en')  # assertions below read English copy (the site default is Nepali)
    path = '/auth/login' if username.startswith('cit') else '/auth/authority/login'
    return client.post(path, data={'username': username, 'password': password})


def body(response):
    text = response.get_data(as_text=True)
    response.close()
    return text


def subscribe(client, browser, who=None):
    if who:
        login(client, who)
    return client.post('/api/push/subscribe', json=browser.json())


def user(app, uid):
    return db.session.get(User, uid)


ADMIN_GETS = ['/admin', '/admin/citizens', '/admin/authorities', '/admin/notifications']


# ============================================================================ admin access

class TestAdminAccess:
    def test_admin_reaches_every_page(self, client, world):
        login(client, 'admin')
        for url in ADMIN_GETS + [f"/admin/citizens/{world['u']['cit_a1']}", f"/admin/authorities/{world['auth_a']}"]:
            assert client.get(url).status_code == 200, url

    @pytest.mark.parametrize('who', ['cit_a1', 'auth_a'])
    def test_citizen_and_authority_denied_everywhere(self, client, world, who):
        login(client, who)
        for url in ADMIN_GETS + [f"/admin/citizens/{world['u']['cit_b']}", f"/admin/authorities/{world['auth_b']}"]:
            assert client.get(url).status_code == 403, url
        for url in (f"/admin/users/{world['u']['cit_b']}/status", f"/admin/users/{world['u']['auth_b']}/reset-password"):
            assert client.post(url, data={'active': '0', 'temporary_password': 'x' * 10,
                                          'confirm_password': 'x' * 10}).status_code == 403

    def test_anonymous_sent_to_login(self, client, world):
        response = client.get('/admin/citizens')
        assert response.status_code == 302 and '/auth/login' in response.headers['Location']

    def test_every_admin_route_is_guarded(self, app, client, world):
        """Any /admin rule added later is covered by the blueprint guard too."""
        login(client, 'cit_a1')
        rules = [r for r in app.url_map.iter_rules() if r.rule.startswith('/admin')]
        assert len(rules) >= 8
        for rule in rules:
            url = re.sub(r'<int:\w+>', '1', rule.rule.replace('<int:user_id>', str(world['u']['cit_b'])).replace(
                '<int:authority_id>', str(world['auth_b'])))
            method = 'POST' if 'POST' in rule.methods and 'GET' not in rule.methods else 'GET'
            assert client.open(url, method=method).status_code == 403, url

    def test_overview_counts_come_from_the_database(self, app, client, world, push):
        login(client, 'cit_a1')
        subscribe(client, Browser('a1'))
        with app.app_context():
            create_hazard_event('flood', 'critical', 'authority', district_id=world['a'])
            from app.services import admin_service
            o = admin_service.overview()
            assert (o['authorities'], o['citizens'], o['districts'], o['active_hazards'], o['push_users']) == (3, 4, 3, 1, 1)
        login(client, 'admin')
        page = body(client.get('/admin'))
        assert 'Push-enabled users' in page and 'Recent emergency events' in page and 'Not implemented' in page


# ============================================================================ authorities

class TestAuthorityManagement:
    def test_list_filter_search_status(self, app, client, world):
        login(client, 'admin')
        page = body(client.get('/admin/authorities'))
        assert all(n in page for n in ('Alpha Office', 'Beta Office', 'Gamma Unlinked Office'))
        page = body(client.get(f"/admin/authorities?district_id={world['b']}"))
        assert 'Beta Office' in page and 'Alpha Office' not in page
        page = body(client.get('/admin/authorities?q=gamma'))
        assert 'Gamma Unlinked Office' in page and 'Beta Office' not in page
        page = body(client.get('/admin/authorities?status=unlinked'))
        assert 'Gamma Unlinked Office' in page and 'Alpha Office' not in page
        with app.app_context():
            user(app, world['u']['auth_b']).is_active = False
            db.session.commit()
        page = body(client.get('/admin/authorities?status=disabled'))
        assert 'Beta Office' in page and 'Alpha Office' not in page
        page = body(client.get('/admin/authorities?status=active'))
        assert 'Alpha Office' in page and 'Beta Office' not in page
        # junk filters are ignored, not errors
        assert client.get('/admin/authorities?district_id=abc&page=-3&status=<x>').status_code == 200

    def test_pagination(self, app, client, world):
        with app.app_context():
            db.session.add_all([Authority(name=f'Zeta Office {i:02d}', category='roads', district_id=world['c'])
                                for i in range(30)])
            db.session.commit()
        login(client, 'admin')
        first = body(client.get(f"/admin/authorities?district_id={world['c']}"))
        second = body(client.get(f"/admin/authorities?district_id={world['c']}&page=2"))
        assert 'Zeta Office 00' in first and 'Zeta Office 23' in first and 'Zeta Office 24' not in first
        assert 'Zeta Office 24' in second and 'Zeta Office 29' in second and 'Zeta Office 00' not in second
        next_link = first.split('rel="next" href="')[1].split('"')[0]
        assert 'page=2' in next_link and f"district_id={world['c']}" in next_link  # filters survive paging

    def test_detail_shows_district_devices_hazards_but_no_secrets(self, app, client, world):
        with app.app_context():
            create_hazard_event('flood', 'high', 'iot', district_id=world['a'], title='Alpha river rising')
            hash_ = user(app, world['u']['auth_a']).password_hash
        login(client, 'admin')
        page = body(client.get(f"/admin/authorities/{world['auth_a']}"))
        assert 'Alpha' in page and 'ESP32-FLOOD-001' in page and 'Alpha river rising' in page and '@auth_a' in page
        assert hash_ not in page and IoTDevice.hash_api_key('device-secret') not in page and 'original-pw' not in page
        assert client.get('/admin/authorities/9999').status_code == 404

    def test_reset_password_flow(self, app, client, world):
        login(client, 'admin')
        uid = world['u']['auth_a']
        with app.app_context():
            old_hash = user(app, uid).password_hash
        response = client.post(f'/admin/users/{uid}/reset-password',
                               data={'temporary_password': 'Temp-Pass-123', 'confirm_password': 'Temp-Pass-123', 'reason': 'test reset'},
                               follow_redirects=True)
        assert response.status_code == 200 and 'Temp-Pass-123' not in body(response)
        with app.app_context():
            u = user(app, uid)
            assert u.must_change_password and u.password_hash != old_hash
            assert 'Temp-Pass-123' not in u.password_hash and u.check_password('Temp-Pass-123')
            assert not u.check_password('original-pw')
            assert u.password_hash not in body(client.get(f"/admin/authorities/{world['auth_a']}"))

        # the temporary password only opens the change-password page
        assert login(client, 'auth_a', 'original-pw').status_code == 200  # old password no longer works
        response = login(client, 'auth_a', 'Temp-Pass-123')
        assert response.status_code == 302 and '/profile/change-password' in response.headers['Location']
        for url in ('/authority/dashboard', '/monitoring', '/notifications'):
            r = client.get(url)
            assert r.status_code == 302 and '/profile/change-password' in r.headers['Location'], url
        assert client.get('/api/notifications').status_code == 403
        assert 'An administrator reset your password' in body(client.get('/profile/change-password'))
        # same password again is refused, short refused, then a real change clears the flag
        assert client.post('/profile/change-password', data={
            'current_password': 'Temp-Pass-123', 'new_password': 'Temp-Pass-123',
            'confirm_password': 'Temp-Pass-123'}).status_code == 400
        assert client.post('/profile/change-password', data={
            'current_password': 'Temp-Pass-123', 'new_password': 'short', 'confirm_password': 'short'}).status_code == 400
        assert client.post('/profile/change-password', data={
            'current_password': 'Temp-Pass-123', 'new_password': 'My-Own-Pass-456',
            'confirm_password': 'My-Own-Pass-456'}).status_code == 302
        with app.app_context():
            assert not user(app, uid).must_change_password
        assert client.get('/authority/dashboard').status_code == 200

    @pytest.mark.parametrize('temp,confirm', [('Temp-Pass-123', 'Other-Pass-123'), ('short', 'short'), ('', '')])
    def test_reset_rejects_bad_temporary_password(self, app, client, world, temp, confirm):
        login(client, 'admin')
        uid = world['u']['auth_a']
        client.post(f'/admin/users/{uid}/reset-password', data={'temporary_password': temp, 'confirm_password': confirm, 'reason': 'test reset'})
        with app.app_context():
            assert user(app, uid).check_password('original-pw') and not user(app, uid).must_change_password

    def test_reset_for_managed_accounts_never_admins(self, app, client, world):
        login(client, 'admin')
        data = {'temporary_password': 'Temp-Pass-123', 'confirm_password': 'Temp-Pass-123', 'reason': 'test reset'}
        # Super Admin release: citizen accounts can be reset too; admin accounts never
        client.post(f"/admin/users/{world['u']['cit_a1']}/reset-password", data=data)
        assert client.post(f"/admin/users/{world['u']['admin']}/reset-password", data=data).status_code == 404
        with app.app_context():
            assert user(app, world['u']['cit_a1']).check_password('Temp-Pass-123')
            assert user(app, world['u']['admin']).check_password('original-pw')

    def test_authority_cannot_reset_another_authority(self, app, client, world):
        login(client, 'auth_a')
        response = client.post(f"/admin/users/{world['u']['auth_b']}/reset-password",
                               data={'temporary_password': 'Temp-Pass-123', 'confirm_password': 'Temp-Pass-123', 'reason': 'test reset'})
        assert response.status_code == 403
        with app.app_context():
            assert user(app, world['u']['auth_b']).check_password('original-pw')

    def test_disable_and_enable_authority_account(self, app, client, world):
        other = app.test_client()

        def as_other(method, url, **kw):
            g.pop('_login_user', None)  # one app context is shared by both test clients
            response = other.open(url, method=method, **kw)
            g.pop('_login_user', None)
            return response

        as_other('POST', '/auth/authority/login', data={'username': 'auth_a', 'password': 'original-pw'})
        assert as_other('GET', '/authority/dashboard').status_code == 200
        login(client, 'admin')
        client.post(f"/admin/users/{world['u']['auth_a']}/status", data={'active': '0', 'reason': 'test', 'confirm': 'DISABLE ACCOUNT'})
        with app.app_context():
            assert user(app, world['u']['auth_a']).is_active is False
        # the open session ends, and login is refused
        assert as_other('GET', '/authority/dashboard').status_code == 302
        as_other('POST', '/auth/authority/login', data={'username': 'auth_a', 'password': 'original-pw'})
        assert as_other('GET', '/authority/dashboard').status_code == 302
        g.pop('_login_user', None)
        login(client, 'admin')
        client.post(f"/admin/users/{world['u']['auth_a']}/status", data={'active': '1', 'reason': 'test'})
        as_other('POST', '/auth/authority/login', data={'username': 'auth_a', 'password': 'original-pw'})
        assert as_other('GET', '/authority/dashboard').status_code == 200

    def test_status_change_validation(self, app, client, world):
        login(client, 'admin')
        assert client.post(f"/admin/users/{world['u']['cit_a1']}/status", data={'active': 'maybe'}).status_code == 400
        assert client.post(f"/admin/users/{world['u']['admin']}/status", data={'active': '0'}).status_code == 404
        assert client.post('/admin/users/9999/status', data={'active': '0'}).status_code == 404
        with app.app_context():
            assert user(app, world['u']['admin']).is_active

    def test_admin_actions_are_logged_without_secrets(self, app, client, world, caplog):
        login(client, 'admin')
        with caplog.at_level('INFO'):
            client.post(f"/admin/users/{world['u']['auth_a']}/reset-password",
                        data={'temporary_password': 'Temp-Pass-123', 'confirm_password': 'Temp-Pass-123', 'reason': 'test reset'})
        assert any('action=RESET_PASSWORD' in r.getMessage() for r in caplog.records)
        assert not any('Temp-Pass-123' in r.getMessage() for r in caplog.records)


# ============================================================================ citizens

class TestCitizenManagement:
    def test_list_and_district_counts(self, app, client, world):
        login(client, 'admin')
        page = body(client.get('/admin/citizens'))
        assert all(f'@{n}' in page for n in ('cit_a1', 'cit_a2', 'cit_b', 'cit_none'))
        assert '@auth_a' not in page and '@admin' not in page
        from app.services import admin_service
        with app.app_context():
            counts = {(r['district'].name if r['district'] else None): r['citizens']
                      for r in admin_service.district_citizen_counts()}
        assert counts == {'Alpha': 2, 'Beta': 1, None: 1}

    def test_district_filter_search_status(self, app, client, world):
        login(client, 'admin')
        page = body(client.get(f"/admin/citizens?district_id={world['a']}"))
        assert '@cit_a1' in page and '@cit_a2' in page and '@cit_b' not in page
        page = body(client.get('/admin/citizens?district_id=0'))
        assert '@cit_none' in page and '@cit_a1' not in page
        page = body(client.get('/admin/citizens?q=A2'))
        assert '@cit_a2' in page and '@cit_a1' not in page
        page = body(client.get('/admin/citizens?q=%25'))  # LIKE wildcards are literal
        assert '@cit_a1' not in page
        with app.app_context():
            user(app, world['u']['cit_b']).is_active = False
            db.session.commit()
        page = body(client.get('/admin/citizens?status=disabled'))
        assert '@cit_b' in page and '@cit_a1' not in page

    def test_pagination(self, app, client, world):
        with app.app_context():
            for i in range(30):
                u = User(username=f'bulk{i:02d}', email=f'bulk{i}@t.np', role='citizen', district_id=world['c'])
                u.set_password('x')
                db.session.add(u)
            db.session.commit()
        login(client, 'admin')
        first = body(client.get(f"/admin/citizens?district_id={world['c']}"))
        second = body(client.get(f"/admin/citizens?district_id={world['c']}&page=2"))
        assert first.count('@bulk') == 25 and second.count('@bulk') == 5
        assert 'Page 1 / 2' in first and '30 citizens' in first

    def test_detail_respects_privacy(self, app, client, world):
        login(client, 'admin')
        page = body(client.get(f"/admin/citizens/{world['u']['cit_a1']}"))
        assert 'cit_a1@t.np' in page and 'Alpha' in page
        assert '27.12' not in page and '85.65' not in page and 'Shared by the citizen' in page
        with app.app_context():
            assert user(app, world['u']['cit_a1']).password_hash not in page
        # citizen pages only show citizens
        assert client.get(f"/admin/citizens/{world['u']['auth_a']}").status_code == 404
        assert client.get(f"/admin/citizens/{world['u']['admin']}").status_code == 404

    def test_disable_citizen(self, app, client, world):
        login(client, 'admin')
        client.post(f"/admin/users/{world['u']['cit_a1']}/status",
                    data={'active': '0', 'reason': 'test', 'confirm': 'DISABLE ACCOUNT'})
        response = login(client, 'cit_a1')
        assert response.status_code == 403 and 'disabled' in body(response)
        assert client.get('/dashboard').status_code == 302


# ============================================================================ push subscriptions

class TestPushSubscriptions:
    def test_subscribe_binds_to_the_logged_in_user(self, app, client, world):
        browser = Browser('one')
        login(client, 'cit_a1')
        payload = browser.json()
        payload['user_id'] = world['u']['cit_b']  # ignored: the server uses the session user
        payload['subscription']['user_id'] = world['u']['cit_b']
        response = client.post('/api/push/subscribe', json=payload)
        assert response.status_code == 201
        text = body(response)
        assert browser.endpoint not in text and browser.auth not in text and browser.p256dh not in text
        assert PRIVATE not in text
        with app.app_context():
            row = PushSubscription.query.one()
            assert row.user_id == world['u']['cit_a1'] and row.enabled
            assert user(app, world['u']['cit_a1']).emergency_alert_state == 'granted'

    def test_duplicate_subscription_updates_one_row(self, app, client, world):
        browser = Browser('dup')
        subscribe(client, browser, 'cit_a1')
        browser.auth = web_push.b64url_encode(os.urandom(16))
        assert subscribe(client, browser).status_code == 201
        with app.app_context():
            rows = PushSubscription.query.all()
            assert len(rows) == 1 and rows[0].auth_key == browser.auth

    def test_same_browser_moves_to_whoever_signs_in(self, app, client, world):
        browser = Browser('shared')
        subscribe(client, browser, 'cit_a1')
        subscribe(client, browser, 'cit_b')
        with app.app_context():
            assert PushSubscription.query.one().user_id == world['u']['cit_b']

    @pytest.mark.parametrize('endpoint', [
        'http://fcm.googleapis.com/fcm/send/x',          # not https
        'https://evil.example/push',                      # not a push service
        'https://127.0.0.1/push', 'https://localhost/x',  # internal targets (SSRF)
        'https://fcm.googleapis.com.evil.example/x',      # suffix trick
        'https://user:pw@fcm.googleapis.com/x',
        'https://fcm.googleapis.com/' + 'x' * 1200,
    ])
    def test_unsafe_endpoints_rejected(self, app, client, world, endpoint):
        browser = Browser('bad')
        browser.endpoint = endpoint
        assert subscribe(client, browser, 'cit_a1').status_code == 400
        with app.app_context():
            assert PushSubscription.query.count() == 0

    def test_mozilla_and_windows_endpoints_accepted(self, client, world):
        login(client, 'cit_a1')
        for endpoint in ('https://updates.push.services.mozilla.com/wpush/v2/abc',
                         'https://wns2-par02p.notify.windows.com/w/?token=abc'):
            browser = Browser('x')
            browser.endpoint = endpoint
            assert subscribe(client, browser).status_code == 201

    @pytest.mark.parametrize('mutate', [
        lambda j: j['subscription']['keys'].update(p256dh='abc'),
        lambda j: j['subscription']['keys'].update(auth='abc'),
        lambda j: j['subscription']['keys'].update(p256dh='BA' + 'A' * 85),  # 65 bytes, not on the curve
        lambda j: j['subscription'].pop('keys'),
        lambda j: j.update(subscription='nope'),
    ])
    def test_invalid_keys_rejected(self, client, world, mutate):
        login(client, 'cit_a1')
        payload = Browser('k').json()
        mutate(payload)
        assert client.post('/api/push/subscribe', json=payload).status_code == 400
        assert client.post('/api/push/subscribe', data='not json').status_code == 400

    def test_push_not_configured(self, app, client, world):
        app.config['VAPID_PRIVATE_KEY'] = ''
        login(client, 'cit_a1')
        assert subscribe(client, Browser('nc')).status_code == 503
        assert client.get('/api/push/config').get_json()['public_key'] is None

    def test_unsubscribe_only_touches_own_rows_and_keeps_history(self, app, client, world):
        mine, theirs = Browser('mine'), Browser('theirs')
        subscribe(client, theirs, 'cit_b')
        subscribe(client, mine, 'cit_a1')
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            history = Notification.query.filter_by(user_id=world['u']['cit_a1']).count()
        response = client.post('/api/push/unsubscribe', json={'endpoint': theirs.endpoint})
        assert response.status_code == 200 and response.get_json()['removed'] == 1
        with app.app_context():
            assert [s.endpoint for s in PushSubscription.query.all()] == [theirs.endpoint]
            assert user(app, world['u']['cit_a1']).emergency_alert_state == 'disabled_by_user'
            assert Notification.query.filter_by(user_id=world['u']['cit_a1']).count() == history == 1

    def test_reported_permission_states(self, app, client, world):
        login(client, 'cit_a1')
        for state in ('denied', 'unsupported', 'not_requested'):
            assert client.post('/api/push/state', json={'state': state}).get_json()['state'] == state
        for bad in ('granted', 'disabled_by_user', 'root', None):
            assert client.post('/api/push/state', json={'state': bad}).status_code == 400
        # an active subscription is not overridden by another device's report
        subscribe(client, Browser('dev1'))
        assert client.post('/api/push/state', json={'state': 'denied'}).get_json()['state'] == 'granted'
        # an explicit opt-out is not overridden either
        client.post('/api/push/unsubscribe', json={})
        assert client.post('/api/push/state', json={'state': 'not_requested'}).get_json()['state'] == 'disabled_by_user'

    def test_test_notification_only_reaches_own_devices(self, app, client, world, push):
        mine, theirs = Browser('mine'), Browser('theirs')
        subscribe(client, theirs, 'cit_b')
        login(client, 'cit_a1')
        assert client.post('/api/push/test').status_code == 409  # nothing to send to yet
        subscribe(client, mine)
        client.get('/auth/logout')
        login(client, 'cit_a1')
        response = client.post('/api/push/test')
        assert response.status_code == 200 and response.get_json() == {'sent': 1, 'devices': 1}
        assert push.to(theirs) == [] and push.to(mine)[0]['title'] == 'X-MAN test notification'
        assert client.post('/api/push/test').status_code == 429

    def test_sound_preference(self, app, client, world):
        login(client, 'cit_a1')
        assert client.post('/api/emergency/sound', json={'enabled': False}).get_json() == {'sound_enabled': False}
        for bad in ('false', 0, None):
            assert client.post('/api/emergency/sound', json={'enabled': bad}).status_code == 400
        with app.app_context():
            assert user(app, world['u']['cit_a1']).emergency_sound_enabled is False

    def test_all_push_routes_need_login(self, client, world):
        for method, url in (('GET', '/api/push/config'), ('POST', '/api/push/subscribe'),
                            ('POST', '/api/push/unsubscribe'), ('POST', '/api/push/state'), ('POST', '/api/push/test'),
                            ('POST', '/api/emergency/sound'), ('GET', '/api/emergency/active')):
            assert client.open(url, method=method, json={}).status_code == 401, url
        assert client.get('/notifications/settings').status_code == 302

    def test_service_worker_served_from_root(self, client):
        response = client.get('/sw.js')
        assert response.status_code == 200 and 'javascript' in response.mimetype
        text = body(response)
        assert "addEventListener('push'" in text and 'showNotification' in text and 'notificationclick' in text


# ============================================================================ dispatch / three layers

def subscribed(client, *names):
    browsers = {}
    for name in names:
        browsers[name] = Browser(name)
        subscribe(client, browsers[name], name)
    return browsers


class TestEmergencyDispatch:
    def test_detection_triggers_all_three_layers_for_the_affected_district(self, app, client, world, push):
        b = subscribed(client, 'cit_a1', 'cit_b', 'auth_a', 'admin')
        with app.app_context():
            incident = create_hazard_event('flood', 'high', 'iot', district_id=world['a'],
                                           title='Alpha river at danger level')
            # layer 1: unchanged M03/M04 targeting
            recipients = {n.user_id for n in Notification.query.filter_by(incident_id=incident.id)}
        u = world['u']
        assert recipients == {u['cit_a1'], u['cit_a2'], u['auth_a'], u['admin']}
        # layer 3: push to the subscribed recipients only; cit_b (other district) gets nothing
        for name in ('cit_a1', 'auth_a', 'admin'):
            [message] = push.to(b[name])
            assert message['emergency'] and message['severity'] == 'high'
            assert message['title'].startswith('X-MAN EMERGENCY ALERT') and 'Alpha' in message['title']
            assert message['url'].startswith('/') and message['tag'] == f'xman-hazard-{incident.id}'
        assert push.to(b['cit_b']) == []
        headers = push.sent[0]['headers']
        assert headers['Content-Encoding'] == 'aes128gcm' and headers['Urgency'] == 'high'
        assert headers['Authorization'].startswith('vapid t=') and f'k={PUBLIC}' in headers['Authorization']
        assert PRIVATE not in json.dumps(headers)
        # layer 2: the in-website alert feed
        login(client, 'cit_a1')
        alerts = client.get('/api/emergency/active').get_json()
        assert [a['hazard']['id'] for a in alerts['alerts']] == [incident.id] and alerts['sound_enabled'] is True
        assert alerts['alerts'][0]['hazard']['affected_districts'] == ['Alpha']
        login(client, 'cit_b')
        assert client.get('/api/emergency/active').get_json()['alerts'] == []

    def test_vapid_jwt_is_valid_es256_for_the_push_origin(self, app, client, world, push):
        subscribed(client, 'cit_a1')
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
        auth = push.sent[0]['headers']['Authorization']
        token = auth.split('t=')[1].split(',')[0]
        header_b64, claims_b64, sig_b64 = token.split('.')
        claims = json.loads(web_push.b64url_decode(claims_b64))
        assert claims['aud'] == 'https://fcm.googleapis.com' and claims['sub'] == 'mailto:ops@x-man.test'
        signature = web_push.b64url_decode(sig_b64)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), web_push.b64url_decode(PUBLIC))
        public.verify(encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')),
                      f'{header_b64}.{claims_b64}'.encode(), ec.ECDSA(hashes.SHA256()))

    def test_repeated_evidence_sends_no_duplicate_push_and_escalation_does(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        with app.app_context():
            incident, created = report_hazard('flood', 'high', 'iot', district_id=world['a'])
            assert created
            for _ in range(3):
                report_hazard('flood', 'high', 'iot', district_id=world['a'])
            assert len(push.to(b['cit_a1'])) == 1
            report_hazard('flood', 'critical', 'iot', district_id=world['a'])
            report_hazard('flood', 'critical', 'iot', district_id=world['a'])
        messages = push.to(b['cit_a1'])
        assert [m['severity'] for m in messages] == ['high', 'critical']
        assert 'CRITICAL' in messages[1]['title']

    def test_below_threshold_is_in_app_only(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        with app.app_context():
            incident = create_hazard_event('landslide', 'medium', 'authority', district_id=world['a'])
            assert Notification.query.filter_by(user_id=world['u']['cit_a1'], incident_id=incident.id).count() == 1
        assert push.to(b['cit_a1']) == []
        login(client, 'cit_a1')
        assert client.get('/api/emergency/active').get_json()['alerts'] == []

    def test_threshold_is_configurable(self, app, client, world, push):
        app.config['EMERGENCY_MIN_SEVERITY'] = 'medium'
        b = subscribed(client, 'cit_a1')
        with app.app_context():
            create_hazard_event('landslide', 'medium', 'authority', district_id=world['a'])
        assert len(push.to(b['cit_a1'])) == 1

    def test_bad_threshold_never_alarms_on_everything(self, app, client, world, push):
        app.config['EMERGENCY_MIN_SEVERITY'] = 'bogus'
        b = subscribed(client, 'cit_a1')
        with app.app_context():
            create_hazard_event('landslide', 'high', 'authority', district_id=world['a'])
            create_hazard_event('flood', 'critical', 'authority', district_id=world['a'])
        assert [m['severity'] for m in push.to(b['cit_a1'])] == ['critical']

    def test_confirmed_and_resolved_follow_the_lifecycle(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        admin = None
        with app.app_context():
            admin = user(app, world['u']['admin'])
            incident = create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            hazard_event_service.transition_event_status(incident, 'investigating', actor_id=admin.id)
            hazard_event_service.transition_event_status(incident, 'confirmed', actor_id=admin.id)
            hazard_event_service.transition_event_status(incident, 'resolved', actor_id=admin.id, note='Water receded')
        messages = push.to(b['cit_a1'])
        assert [m['emergency'] for m in messages] == [True, True, False]
        assert 'resolved' in messages[2]['title'] and 'Water receded' not in json.dumps(messages)
        assert [s['headers']['Urgency'] for s in push.sent] == ['high', 'high', 'normal']
        login(client, 'cit_a1')
        assert client.get('/api/emergency/active').get_json()['alerts'] == []  # hazard no longer active

    def test_area_expansion_reaches_newly_affected_citizens_once(self, app, client, world, push):
        b = subscribed(client, 'cit_a1', 'cit_b')
        with app.app_context():
            incident = create_hazard_event('flood', 'critical', 'authority', district_id=world['a'])
            hazard_event_service.add_affected_district(incident, world['b'])
        assert len(push.to(b['cit_b'])) == 1 and len(push.to(b['cit_a1'])) == 1

    def test_opted_out_disabled_and_unsubscribed_users_get_no_push(self, app, client, world, push):
        b = subscribed(client, 'cit_a1', 'cit_a2', 'auth_a')
        with app.app_context():
            user(app, world['u']['cit_a1']).emergency_alert_state = 'disabled_by_user'
            user(app, world['u']['cit_a2']).is_active = False
            db.session.commit()
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            # in-app history is still written for everyone affected
            assert Notification.query.filter_by(user_id=world['u']['cit_a1']).count() == 1
        assert push.to(b['cit_a1']) == [] and push.to(b['cit_a2']) == [] and len(push.to(b['auth_a'])) == 1

    def test_muted_citizen_still_gets_visual_alert_record_and_push(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        client.post('/api/emergency/sound', json={'enabled': False})
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            assert Notification.query.filter_by(user_id=world['u']['cit_a1']).count() == 1
        assert len(push.to(b['cit_a1'])) == 1
        feed = client.get('/api/emergency/active').get_json()
        assert len(feed['alerts']) == 1 and feed['sound_enabled'] is False

    def test_reading_the_alert_removes_it_from_the_website_layer(self, app, client, world):
        login(client, 'cit_a1')
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
        [alert] = client.get('/api/emergency/active').get_json()['alerts']
        client.post(f"/api/notifications/{alert['id']}/read")
        assert client.get('/api/emergency/active').get_json()['alerts'] == []

    def test_expired_subscription_is_disabled_and_hazard_stays(self, app, client, world, push):
        b = subscribed(client, 'cit_a1', 'auth_a')
        push.status[b['cit_a1'].endpoint] = 410
        with app.app_context():
            incident = create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
            assert db.session.get(Incident, incident.id) is not None
            rows = {s.endpoint: s for s in PushSubscription.query}
            assert rows[b['cit_a1'].endpoint].enabled is False and rows[b['auth_a'].endpoint].enabled is True
            # a disabled subscription is skipped next time
            report_hazard('flood', 'critical', 'authority', district_id=world['a'])
        assert len([s for s in push.sent if s['endpoint'] == b['cit_a1'].endpoint]) == 1

    def test_repeated_failures_disable_after_limit(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        push.status[b['cit_a1'].endpoint] = 500
        with app.app_context():
            sub = PushSubscription.query.one()
            for _ in range(emergency_dispatcher.MAX_FAILURES):
                assert sub.enabled
                emergency_dispatcher._send(sub, {'emergency': True})
            assert sub.enabled is False

    def test_push_failure_never_breaks_hazard_creation(self, app, client, world, push, caplog):
        b = subscribed(client, 'cit_a1')
        import requests
        push.raise_error = requests.ConnectionError(f'cannot reach {b["cit_a1"].endpoint}')
        with app.app_context(), caplog.at_level('INFO'):
            incident = create_hazard_event('flood', 'critical', 'authority', district_id=world['a'])
            assert db.session.get(Incident, incident.id).severity == 'critical'
            assert PushSubscription.query.one().failure_count == 1
            # an unexpected error inside the dispatcher is contained too
            push.raise_error = None
            original = web_push.encrypt
            web_push.encrypt = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
            try:
                report_hazard('flood', 'critical', 'authority', district_id=world['b'])
            finally:
                web_push.encrypt = original
            assert Incident.query.count() == 2
        log = ' '.join(r.getMessage() for r in caplog.records)
        assert b['cit_a1'].endpoint not in log and b['cit_a1'].auth not in log

    def test_rolled_back_notifications_are_never_pushed(self, app, client, world, push):
        subscribed(client, 'cit_a1')
        with app.app_context():
            incident = Incident(event_type='flood', severity='high', source='authority', district_id=world['a'],
                                status='detected')
            db.session.add(incident)
            db.session.flush()
            notification_service.notify_hazard_detected(incident)
            db.session.rollback()  # e.g. a later validation failure; nothing was committed
            assert emergency_dispatcher.flush() == 0
            assert Notification.query.count() == 0
        assert push.sent == []

    def test_payload_has_only_public_fields(self, app, client, world, push):
        b = subscribed(client, 'cit_a1')
        with app.app_context():
            create_hazard_event('flood', 'high', 'citizen_report', district_id=world['a'], title='Bridge flooded',
                                description='PRIVATE reporter note', source_reference='report:42')
        text = json.dumps(push.to(b['cit_a1']))
        assert 'PRIVATE' not in text and 'report:42' not in text and 'Bridge flooded' in text


# ============================================================================ pages, privacy, CSRF, XSS

class TestPagesAndSecurity:
    def test_settings_page_explains_and_never_auto_prompts(self, client, world):
        login(client, 'cit_a1')
        page = body(client.get('/notifications/settings'))
        assert 'Turn Off Emergency Alerts' in page and 'Test Emergency Notification' in page
        assert 'X-MAN notification records remain available in your account' in page
        assert 'Guaranteed' not in page and 'network connectivity' in page
        assert PUBLIC in page and PRIVATE not in page
        # permission is only requested from the click handler in emergency.js, never inline on load
        assert 'requestPermission' not in page

    def test_dashboard_offers_opt_in_with_the_required_explanation(self, client, world):
        login(client, 'cit_a1')
        page = body(client.get('/dashboard'))
        assert 'X-MAN can send emergency disaster alerts even when this website is closed.' in page
        assert 'Enable Emergency Alerts' in page and 'Not Now' in page and 'requestPermission' not in page
        subscribe(client, Browser('d'))
        assert 'id="emergency-optin"' not in body(client.get('/dashboard'))  # decided: no more prompt

    def test_emergency_script_requests_permission_only_on_click(self, client):
        script = body(client.get('/static/js/emergency.js'))
        assert script.count('Notification.requestPermission(') == 1
        assert 'enable: function' in script.split('Notification.requestPermission(')[0].rsplit('XmanPush = {', 1)[1]
        assert 'textContent' in script and 'innerHTML' not in script
        assert 'ALARM_CYCLES' in script and 'stopAlarm' in script

    def test_alert_overlay_only_for_signed_in_users(self, client, world):
        assert 'xman-emergency' not in body(client.get('/auth/login'))
        login(client, 'cit_a1')
        page = body(client.get('/dashboard'))
        assert 'id="xman-emergency"' in page and 'Mute alarm' in page and 'View hazard' in page

    def test_private_vapid_key_never_reaches_any_page_or_api(self, app, client, world):
        for who in ('cit_a1', 'auth_a', 'admin'):
            login(client, who)
            for url in ('/dashboard', '/notifications/settings', '/api/push/config', '/admin', '/admin/notifications',
                        '/authority/dashboard', '/monitoring', '/static/js/emergency.js', '/sw.js'):
                assert PRIVATE not in body(client.get(url)), (who, url)

    def test_subscription_secrets_never_in_admin_pages(self, app, client, world):
        browser = Browser('secret')
        subscribe(client, browser, 'cit_a1')
        login(client, 'admin')
        for url in ('/admin/citizens', f"/admin/citizens/{world['u']['cit_a1']}", '/admin/notifications', '/admin'):
            text = body(client.get(url))
            assert browser.endpoint not in text and browser.auth not in text and browser.p256dh not in text

    def test_admin_pages_escape_user_content(self, app, client, world):
        with app.app_context():
            db.session.get(Authority, world['auth_a']).name = '<script>alert(1)</script>'
            user(app, world['u']['cit_a1']).full_name = '<img src=x onerror=alert(1)>'
            db.session.commit()
        login(client, 'admin')
        for url in ('/admin/authorities', f"/admin/authorities/{world['auth_a']}", '/admin/citizens',
                    f"/admin/citizens/{world['u']['cit_a1']}"):
            text = body(client.get(url))
            assert '<script>alert(1)</script>' not in text and '<img src=x' not in text, url

    def test_csrf_enforced_on_admin_and_push_posts(self, world):
        app = create_app('testing')
        app.config.update(WTF_CSRF_ENABLED=True, VAPID_PUBLIC_KEY=PUBLIC, VAPID_PRIVATE_KEY=PRIVATE)
        with app.app_context():
            db.create_all()
            admin = User(username='root', email='root@t.np', role='admin')
            admin.set_password('pw')
            db.session.add(admin)
            db.session.commit()
            client = app.test_client()
            with client.session_transaction() as s:
                s['_user_id'] = str(admin.id)
                s['_fresh'] = True
            assert client.post(f'/admin/users/{admin.id}/status', data={'active': '0'}).status_code == 400
            assert client.post('/api/push/subscribe', json=Browser('c').json()).status_code == 400
            assert client.post('/api/emergency/sound', json={'enabled': False}).status_code == 400
            assert PushSubscription.query.count() == 0
            db.session.remove()
            db.drop_all()


def test_fresh_install_has_m12_schema(tmp_path):
    """Fresh install (init_db.py, stamped at head) has the M12 schema and matches the migrations.
    Upgrade/downgrade of the M12 head itself is covered by test_security_m10's fresh-install test."""
    path = tmp_path / 'm12.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path.as_posix()}', 'FLASK_APP': 'run.py',
           'VISION_ENABLED': 'false', 'PYTHONIOENCODING': 'utf-8'}

    def run(*args):
        return subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)

    assert run('init_db.py').returncode == 0
    current = run('-m', 'flask', 'db', 'current')
    assert '(head)' in current.stdout + current.stderr  # M12 or a later additive head (Super Admin)
    assert run('-m', 'flask', 'db', 'check').returncode == 0
    import sqlite3
    con = sqlite3.connect(path)
    columns = {row[1] for row in con.execute('PRAGMA table_info(users)')}
    assert {'is_active', 'must_change_password', 'last_login_at', 'emergency_alert_state',
            'emergency_sound_enabled'} <= columns
    push_columns = {row[1] for row in con.execute('PRAGMA table_info(push_subscriptions)')}
    assert {'endpoint', 'p256dh_key', 'auth_key', 'enabled', 'last_used_at'} <= push_columns
    con.close()


def test_rfc8291_test_vector():
    """Byte-exact against RFC 8291 Appendix A."""
    sender = ec.derive_private_key(int.from_bytes(
        web_push.b64url_decode('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), ec.SECP256R1())
    body_ = web_push.encrypt(b'When I grow up, I want to be a watermelon',
                             'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
                             'BTBZMqHH6r4Tts7J_aSIgg', salt=web_push.b64url_decode('DGv6ra1nlYgDCS1FRnbzlw'),
                             sender_key=sender)
    assert web_push.b64url_encode(body_) == (
        'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEq'
        'KK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')
