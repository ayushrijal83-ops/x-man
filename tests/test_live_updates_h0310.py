"""H03.10 live UI: the polling endpoints (/api/emergency/active status, /api/dashboard, /admin/devices/status.json)
and same-route live regions (device detail, dashboards, notification list).

Polling only reads: it must never create notifications or pushes, must keep every role/district scope, and
must not leak credentials. The browser scheduler itself (live.js) is exercised in tests/live_harness.js.
"""
import json
import os
import re
import subprocess
from html.parser import HTMLParser

import pytest
from flask import g

from app.extensions import db
from app.models import Authority, District, Incident, IoTDevice, Notification, PushSubscription, User
from app.services import emergency_dispatcher, hazard_event_service

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def world(app):
    a, b = District(name='Sindhuli', province='P'), District(name='Kathmandu', province='P')
    db.session.add_all([a, b])
    db.session.commit()
    auth_a = Authority(name='Sindhuli DAO', category='disaster', district_id=a.id)
    auth_b = Authority(name='KTM DAO', category='disaster', district_id=b.id)
    db.session.add_all([auth_a, auth_b])
    db.session.commit()
    users = {}
    for name, role, district, authority in [('citizen_a', 'citizen', a, None), ('citizen_b', 'citizen', b, None),
                                            ('auth_a', 'authority', a, auth_a), ('auth_b', 'authority', b, auth_b),
                                            ('admin', 'admin', None, None)]:
        u = User(username=name, email=f'{name}@t.np', role=role, district_id=district.id if district else None,
                 authority_id=authority.id if authority else None, language='en')
        u.set_password('pw')
        db.session.add(u)
        users[name] = u
    keys = {}
    for dev_id, district, authority in [('ESP32-SEISMIC-T1', a, auth_a), ('ESP32-OTHER-T2', b, auth_b)]:
        key = IoTDevice.generate_api_key()
        db.session.add(IoTDevice(device_id=dev_id, name=dev_id, district_id=district.id, authority_id=authority.id,
                                 api_key_hash=IoTDevice.hash_api_key(key), status='active', enabled=True))
        keys[dev_id] = key
    db.session.commit()
    return {'a': a.id, 'b': b.id, 'u': {k: v.id for k, v in users.items()}, 'keys': keys,
            'dev': {d.device_id: d.id for d in IoTDevice.query.all()}}


def login(client, username):
    g.pop('_login_user', None)
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})
    g.pop('_login_user', None)


def send(client, world, device, value):
    return client.post('/api/iot/telemetry', json={'readings': [{'sensor_type': 'vibration', 'value': value, 'unit': 'mg'}]},
                       headers={'Authorization': f"Bearer {device}:{world['keys'][device]}"})


def status(client):
    r = client.get('/api/emergency/active')
    return r.status_code, (r.get_json() if r.is_json else None), r


def hazard(world, severity='medium', district='a'):
    return hazard_event_service.create_hazard_event('landslide', severity, 'authority', district_id=world[district],
                                                    title='Test landslide')


# --- global status poll (/api/emergency/active) ------------------------------------------------

class TestStatusPoll:
    def test_requires_login(self, client, world):
        code, data, _ = status(client)
        assert code == 401 and 'unread_count' not in (data or {})

    def test_unread_count_and_latest_are_own_only(self, client, world):
        login(client, 'citizen_a')
        _, before, r = status(client)
        assert before['unread_count'] == 0 and before['latest_notification_id'] is None
        assert r.headers['Cache-Control'] == 'private, no-store'
        hazard(world)  # notifies district A users + admins
        _, after, _ = status(client)
        mine = Notification.query.filter_by(user_id=world['u']['citizen_a']).one()
        assert after['unread_count'] == 1 and after['latest_notification_id'] == mine.id
        login(client, 'citizen_b')  # other district: nothing
        _, other, _ = status(client)
        assert other['unread_count'] == 0 and other['latest_notification_id'] is None

    def test_read_state_becomes_visible(self, client, world):
        hazard(world)
        login(client, 'citizen_a')
        nid = status(client)[1]['latest_notification_id']
        client.post(f'/api/notifications/{nid}/read', json={})
        assert status(client)[1]['unread_count'] == 0

    def test_emergency_state_becomes_visible_in_scope_only(self, client, world):
        login(client, 'citizen_a')
        assert status(client)[1]['alerts'] == []
        hazard(world, severity='high')
        alerts = status(client)[1]['alerts']
        assert len(alerts) == 1 and alerts[0]['severity'] == 'high'
        login(client, 'citizen_b')
        assert status(client)[1]['alerts'] == []

    def test_polling_never_creates_notifications_or_pushes(self, app, client, world, monkeypatch):
        app.config.update(VAPID_PUBLIC_KEY='pub', VAPID_PRIVATE_KEY='priv')
        pushes = []
        monkeypatch.setattr(emergency_dispatcher, '_send', lambda s, p: pushes.append(p) or True)
        user = db.session.get(User, world['u']['citizen_a'])
        user.emergency_alert_state = 'granted'
        db.session.add(PushSubscription(user_id=user.id, endpoint='https://fcm.googleapis.com/fcm/send/x', p256dh_key='k', auth_key='a'))
        db.session.commit()
        hazard(world, severity='high')
        notes, sent = Notification.query.count(), len(pushes)
        login(client, 'citizen_a')
        for _ in range(25):
            assert status(client)[0] == 200
            client.get('/notifications/settings')
        assert Notification.query.count() == notes and len(pushes) == sent

    def test_no_secrets_in_status(self, client, world):
        db.session.add(PushSubscription(user_id=world['u']['citizen_a'], endpoint='https://fcm.googleapis.com/fcm/send/SECRET-EP',
                                        p256dh_key='SECRET-P256', auth_key='SECRET-AUTH'))
        db.session.commit()
        hazard(world, severity='critical')
        login(client, 'citizen_a')
        body = status(client)[2].get_data(as_text=True)
        assert 'SECRET' not in body and 'source_reference' not in body


# --- /monitoring JSON (/api/dashboard) --------------------------------------------------------------

def device_entry(payload, device_id):
    return next((d for d in payload.get('devices', []) if d['device_id'] == device_id), None)


class TestDashboardPoll:
    def test_new_telemetry_becomes_visible(self, client, world):
        login(client, 'admin')
        assert device_entry(client.get('/api/dashboard').get_json(), 'ESP32-SEISMIC-T1')['readings'] == []
        assert send(client, world, 'ESP32-SEISMIC-T1', 71.5).status_code == 201
        login(client, 'admin')
        d = device_entry(client.get('/api/dashboard').get_json(), 'ESP32-SEISMIC-T1')
        assert d['readings'][0]['value'] == 71.5 and d['freshness'] == 'online' and d['last_seen']
        send(client, world, 'ESP32-SEISMIC-T1', 12.25)
        login(client, 'admin')
        assert device_entry(client.get('/api/dashboard').get_json(), 'ESP32-SEISMIC-T1')['readings'][0]['value'] == 12.25

    def test_disabled_device_becomes_visible(self, client, world):
        login(client, 'admin')
        assert device_entry(client.get('/api/dashboard').get_json(), 'ESP32-SEISMIC-T1')['enabled'] is True
        r = client.post(f"/admin/devices/{world['dev']['ESP32-SEISMIC-T1']}/status",
                        data={'enabled': '0', 'reason': 'H03.10 test', 'confirm': 'DISABLE DEVICE'})
        assert r.status_code == 302
        assert device_entry(client.get('/api/dashboard').get_json(), 'ESP32-SEISMIC-T1')['enabled'] is False

    def test_role_and_district_scoping(self, client, world):
        send(client, world, 'ESP32-SEISMIC-T1', 50)
        login(client, 'citizen_a')
        p = client.get('/api/dashboard').get_json()
        assert 'devices' not in p and 'statistics' not in p and p['scope']['district']['id'] == world['a']
        login(client, 'auth_a')
        p = client.get('/api/dashboard').get_json()
        assert [d['device_id'] for d in p['devices']] == ['ESP32-SEISMIC-T1'] and 'statistics' not in p
        login(client, 'auth_b')
        assert [d['device_id'] for d in client.get('/api/dashboard').get_json()['devices']] == ['ESP32-OTHER-T2']
        login(client, 'admin')
        assert {d['device_id'] for d in client.get('/api/dashboard').get_json()['devices']} == {'ESP32-SEISMIC-T1', 'ESP32-OTHER-T2'}

    def test_unauthorized_and_malformed(self, client, world):
        assert client.get('/api/dashboard').status_code == 401
        login(client, 'citizen_a')
        for bad in ('abc', '-1', '0', '1.5', '99999999999999999999'):
            assert client.get(f'/api/dashboard?district_id={bad}').status_code in (400, 403, 404), bad
        body = client.get('/api/dashboard').get_data(as_text=True)
        assert world['keys']['ESP32-SEISMIC-T1'] not in body and 'api_key' not in body


# --- Super Admin device list (/admin/devices/status.json) -----------------------------------------------

class TestDeviceStatusPoll:
    URL = '/admin/devices/status.json'

    def test_admin_only(self, client, world):
        assert client.get(self.URL).status_code in (302, 401)
        for who in ('citizen_a', 'auth_a'):
            login(client, who)
            assert client.get(self.URL).status_code == 403

    def test_state_and_last_seen_become_visible(self, client, world):
        pk = str(world['dev']['ESP32-SEISMIC-T1'])
        login(client, 'admin')
        data = client.get(self.URL).get_json()
        assert data['states'][pk] == 'never' and data['last_seen'][pk] is None
        send(client, world, 'ESP32-SEISMIC-T1', 70)
        login(client, 'admin')
        r = client.get(self.URL)
        data = r.get_json()
        assert data['states'][pk] == 'online' and re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d', data['last_seen'][pk])
        assert r.headers['Cache-Control'] == 'private, no-store'
        client.post(f'/admin/devices/{pk}/status', data={'enabled': '0', 'reason': 'H03.10', 'confirm': 'DISABLE DEVICE'})
        assert client.get(self.URL).get_json()['states'][pk] == 'disabled'
        body = client.get(self.URL).get_data(as_text=True)
        assert world['keys']['ESP32-SEISMIC-T1'] not in body and 'hash' not in body


# --- same-route live regions -----------------------------------------------------------------------------

class LiveRegions(HTMLParser):
    """Collects data-live keys and whether any form control is inside a live region."""

    def __init__(self):
        super().__init__()
        self.stack, self.keys, self.controls_inside = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('input', 'select', 'textarea', 'form') and any(self.stack):
            self.controls_inside.append(tag)
        if tag in ('input', 'br', 'img', 'meta', 'link', 'hr'):
            return
        if 'data-live' in a:
            self.keys.append(a['data-live'])
        self.stack.append('data-live' in a)

    def handle_endtag(self, tag):
        if tag not in ('input', 'br', 'img', 'meta', 'link', 'hr') and self.stack:
            self.stack.pop()


def regions(html):
    p = LiveRegions()
    p.feed(html)
    return p


class TestLiveRegions:
    def test_device_detail_shows_new_telemetry_and_state_on_refetch(self, client, world):
        pk = world['dev']['ESP32-SEISMIC-T1']
        login(client, 'admin')
        page = client.get(f'/admin/devices/{pk}').get_data(as_text=True)
        assert 'data-live-interval="5000"' in page
        r = regions(page)
        assert {'device-banner', 'device-info', 'latest', 'history', 'history-total'} <= set(r.keys)
        assert r.controls_inside == []  # forms (control panel, filters) are never inside a live region
        send(client, world, 'ESP32-SEISMIC-T1', 64.75)
        login(client, 'admin')
        fresh = client.get(f'/admin/devices/{pk}', headers={'X-Xman-Live': '1'}).get_data(as_text=True)
        latest = re.search(r'data-live="latest">(.*?)</div>\s*</section>', fresh, re.S).group(1)
        assert '64.75' in latest and 'vibration' in latest
        client.post(f'/admin/devices/{pk}/status', data={'enabled': '0', 'reason': 'H03.10', 'confirm': 'DISABLE DEVICE'})
        fresh = client.get(f'/admin/devices/{pk}', headers={'X-Xman-Live': '1'}).get_data(as_text=True)
        banner = re.search(r'data-live="device-banner">(.*?)</div>\s*<div class="bento">', fresh, re.S).group(1)
        assert 'Device disabled by Super Admin' in banner

    def test_live_refetch_keeps_route_authorization(self, client, world):
        pk = world['dev']['ESP32-SEISMIC-T1']
        for who in ('citizen_a', 'auth_a'):
            login(client, who)
            assert client.get(f'/admin/devices/{pk}', headers={'X-Xman-Live': '1'}).status_code == 403
        client.get('/auth/logout')
        r = client.get(f'/admin/devices/{pk}', headers={'X-Xman-Live': '1'})
        assert r.status_code == 302 and '/auth/' in r.headers['Location']  # the client never swaps a redirect

    def test_one_time_key_never_reappears_on_live_refetch(self, client, world):
        login(client, 'admin')
        r = client.post('/admin/devices/new', data={'device_id': 'LIVE-KEY-1', 'name': 'k', 'district_id': world['a'],
                                                     'kind': 'sensor', 'monitoring': 'other', 'reason': 'H03.10'})
        first = client.get(r.headers['Location']).get_data(as_text=True)
        key = re.search(r'class="secret-once".*?<code>([A-Za-z0-9_-]{40,})</code>', first, re.S).group(1)
        assert 'secret-once' not in ' '.join(regions(first).keys)
        again = client.get(r.headers['Location'], headers={'X-Xman-Live': '1'}).get_data(as_text=True)
        assert key not in again

    @pytest.mark.parametrize('who, url, interval', [('citizen_a', '/dashboard', '30000'),
                                                    ('auth_a', '/authority/dashboard', '30000'),
                                                    ('admin', '/admin', '30000')])
    def test_dashboards_refresh_cards_but_never_forms_or_maps(self, client, world, who, url, interval):
        login(client, who)
        page = client.get(url).get_data(as_text=True)
        assert f'data-live-interval="{interval}"' in page
        r = regions(page)
        assert r.keys and r.controls_inside == []
        assert 'h-map' not in r.keys and 'h-choose' not in r.keys

    def test_dashboard_card_shows_new_hazard_on_refetch(self, client, world):
        login(client, 'citizen_a')
        before = client.get('/dashboard').get_data(as_text=True)
        assert 'Test landslide' not in before
        hazard(world)
        after = client.get('/dashboard', headers={'X-Xman-Live': '1'}).get_data(as_text=True)
        assert 'Test landslide' in re.search(r'data-live="h-hazards">(.*?)</section>', after, re.S).group(1)

    def test_notification_list_refreshes_on_status_change(self, client, world):
        login(client, 'citizen_a')
        page = client.get('/notifications').get_data(as_text=True)
        assert 'data-live-on="notifications"' in page and 'data-live-interval' not in page
        assert {'notif-list', 'notif-actions'} <= set(regions(page).keys)
        hazard(world)
        fresh = client.get('/notifications', headers={'X-Xman-Live': '1'}).get_data(as_text=True)
        assert 'Landslide detected in Sindhuli' in fresh and 'id="read-all"' in fresh
        login(client, 'citizen_b')
        assert 'Landslide detected' not in client.get('/notifications').get_data(as_text=True)


# --- one scheduler, no duplicate loops ---------------------------------------------------------------------

class TestClientWiring:
    def test_scheduler_loaded_once_for_signed_in_pages_only(self, client, world):
        assert 'js/live.js' not in client.get('/').get_data(as_text=True)
        login(client, 'citizen_a')
        page = client.get('/dashboard').get_data(as_text=True)
        assert page.count('js/live.js') == 1 and page.index('js/live.js') < page.index('js/emergency.js')

    def test_no_ad_hoc_polling_loops_remain(self):
        sources = {}
        for root in ('app/templates', 'app/static/js'):
            for dirpath, _, files in os.walk(os.path.join(REPO, root)):
                for f in files:
                    if f.endswith(('.html', '.js')):
                        sources[f] = open(os.path.join(dirpath, f), encoding='utf-8').read()
        # the only setInterval left is the alarm beep pattern, not a data poll
        intervals = {f: re.findall(r'setInterval\(([^,]+)', s) for f, s in sources.items() if 'setInterval(' in s}
        assert intervals == {'emergency.js': ['cycle']}
        em = sources['emergency.js']
        assert "XmanLive.every('status', POLL_MS, poll, { hiddenMs: HIDDEN_POLL_MS })" in em
        assert 'var POLL_MS = 10000;' in em and 'var HIDDEN_POLL_MS = 60000;' in em
        assert "XmanLive.every('device-states', 10000, poll)" in sources['devices.html']

    def test_scheduler_behaviour_in_node(self):
        out = subprocess.run(['node', os.path.join(REPO, 'tests', 'live_harness.js')], capture_output=True, text=True,
                             timeout=60)
        assert out.returncode == 0, out.stderr
        r = json.loads(out.stdout)
        assert r['noOverlap'] == {'startsWhileRunning': 1, 'nextDelay': 10000, 'startsAfterInterval': 2}
        assert r['duplicate'] == {'sameLoop': True, 'secondTaskCalls': 0}
        assert r['visibility'] == {'timersWhileHidden': 0, 'callsWhileHidden': 0, 'callsAfterVisible': 2}
        assert r['hiddenSlow'] == {'delay': 60000, 'calls': 2}
        assert r['backoff']['delays'] == [20000, 40000, 60000, 60000, 60000]
        assert r['backoff']['afterRecoveryNext'] == 10000 and r['backoff']['syncThrowScheduled']
        reg = r['regions']
        assert reg['afterChange'] == ['A', 'B-changed'] and reg['afterRedirectAndError'] == ['A', 'B-changed']
        assert reg['redirectRejected'] and reg['errorRejected'] and reg['events'] == ['updated']
        assert reg['liveHeader'] == '1' and reg['url'] == 'https://x-man.example/page'


    def test_status_poll_detects_first_notification_and_drives_badge(self):
        """Regression (found in browser QA): a user with NO notification gets latest_notification_id = null; the
        first notification after that must refresh the list. Runs the real emergency.js poll in Node."""
        out = subprocess.run(['node', os.path.join(REPO, 'tests', 'emergency_status_harness.js')], capture_output=True,
                             text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        r = json.loads(out.stdout)
        assert r['loop'] == {'name': 'status', 'ms': 10000, 'hiddenMs': 60000}
        assert r['changed'] == [False, True, False, True, False]
        assert [(b['text'], b['hidden'], b['page']) for b in r['badges']] == [
            ('0', True, '0'), ('1', False, '1'), ('1', False, '1'), ('2', False, '2'), ('0', True, '0')]
