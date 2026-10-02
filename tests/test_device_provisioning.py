"""H01.5 Super Admin IoT device provisioning: register (district + explicit river, server-owned),
one-time API key display, audit, PATCH-equivalent edit, and the telemetry -> district -> hazard ->
notification path for a device registered through the UI. No hardware involved."""
import re

import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.models import AuditLog, Authority, District, Incident, IoTDevice, Notification, River, User

KEY_RE = r'class="secret-once".*?<code>([A-Za-z0-9_-]{40,})</code>'


@pytest.fixture
def app():
    app = create_app('testing')
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
    ktm, ltp = District(name='Kathmandu', province='Bagmati'), District(name='Lalitpur', province='Bagmati')
    db.session.add_all([ktm, ltp])
    db.session.flush()
    rivers = [River(name='Bagmati River', district_id=ktm.id, danger_level=3.5),
              River(name='Bishnumati River', district_id=ktm.id, danger_level=3.0),
              River(name='Bagmati River', district_id=ltp.id, danger_level=3.5)]
    office = Authority(name='KTM DAO', category='disaster', district_id=ktm.id)
    db.session.add_all(rivers + [office])
    db.session.flush()
    for name, role, district, authority in [('root', 'admin', None, None), ('cit_k', 'citizen', ktm, None),
                                            ('cit_l', 'citizen', ltp, None), ('auth_k', 'authority', ktm, office)]:
        user = User(username=name, email=f'{name}@t.np', role=role, district_id=district.id if district else None,
                    authority_id=authority.id if authority else None, language='en')
        user.set_password('pw-12345678')
        db.session.add(user)
    db.session.commit()
    return {'ktm': ktm.id, 'ltp': ltp.id, 'bagmati': rivers[0].id, 'bishnumati': rivers[1].id,
            'bagmati_ltp': rivers[2].id}


def login(client, username):
    g.pop('_login_user', None)
    client.get('/auth/logout')
    client.get('/language/set/en')
    path = '/auth/login' if username.startswith('cit') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw-12345678'})
    g.pop('_login_user', None)


def text(response):
    body = response.get_data(as_text=True)
    response.close()
    return body


def shown_key(page):
    match = re.search(KEY_RE, page, re.S)
    return match.group(1) if match else None


def form(world, **over):
    data = {'device_id': 'ESP32-FLOOD-001', 'name': 'Bagmati bridge node', 'district_id': world['ktm'],
            'river_id': world['bagmati'], 'monitoring': 'water_level', 'latitude': '27.7', 'longitude': '85.3',
            'location_description': 'Thapathali bridge', 'firmware_version': '1.0.0', 'description': 'JSN-SR04T',
            'reason': 'H01.5 provisioning'}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def register(client, world, **over):
    return client.post('/admin/devices/new', data=form(world, **over))


def device():
    db.session.expire_all()
    return IoTDevice.query.filter_by(device_id='ESP32-FLOOD-001').first()


def telemetry(client, key, payload):
    return client.post('/api/iot/telemetry', json=payload, headers={'Authorization': f'Bearer ESP32-FLOOD-001:{key}'})


class TestAccess:
    def test_admin_opens_registration_page(self, client, world):
        login(client, 'root')
        page = text(client.get('/admin/devices/new'))
        assert 'Register device' in page and 'Kathmandu' in page
        assert '>Bagmati River (danger level 3.5 m)</option>' not in page  # rivers follow the chosen district
        assert 'Register device' in text(client.get('/admin/devices'))

    @pytest.mark.parametrize('who', ['cit_k', 'auth_k'])
    def test_citizen_and_authority_are_refused(self, client, world, who):
        login(client, who)
        assert client.get('/admin/devices/new').status_code == 403
        assert register(client, world).status_code == 403
        assert device() is None and AuditLog.query.count() == 0

    def test_anonymous_redirected_to_login(self, client, world):
        response = register(client, world)
        assert response.status_code == 302 and '/auth/login' in response.headers['Location']
        assert device() is None

    def test_csrf_required(self, world):
        app = create_app('testing')
        app.config.update(WTF_CSRF_ENABLED=True)
        with app.app_context():
            db.create_all()
            root = User(username='rootx', email='rootx@t.np', role='admin')
            root.set_password('pw')
            d = District(name='Z', province='P')
            db.session.add_all([root, d])
            db.session.commit()
            c = app.test_client()
            with c.session_transaction() as s:
                s['_user_id'] = root.get_id()
                s['_fresh'] = True
            assert c.post('/admin/devices/new', data=form({'ktm': d.id, 'bagmati': None},
                                                          monitoring='other')).status_code == 400
            assert IoTDevice.query.count() == 0
            db.session.remove()
            db.drop_all()


class TestRegistration:
    def test_valid_registration_shows_key_once(self, app, client, world, caplog):
        login(client, 'root')
        with caplog.at_level('DEBUG'):
            response = register(client, world)
            dev = device()
            assert response.status_code == 302 and response.headers['Location'].endswith(f'/admin/devices/{dev.id}')
            assert 'api_key' not in response.headers['Location'] and shown_key(text(response)) is None
            assert (dev.district_id, dev.river_id, dev.latitude, dev.longitude) == (world['ktm'], world['bagmati'],
                                                                                   27.7, 85.3)
            assert dev.enabled and dev.status == 'active' and dev.authority_id is None
            first = client.get(f'/admin/devices/{dev.id}')
            assert first.headers['Cache-Control'] == 'no-store'
            page = text(first)
            key = shown_key(page)
            assert key and IoTDevice.hash_api_key(key) == dev.api_key_hash
            assert 'Kathmandu' in page and 'Bagmati River' in page
            assert not any(key in b for b in re.findall(r'<script.*?</script>', page, re.S))
            # reload / revisit: never again
            for url in (f'/admin/devices/{dev.id}', '/admin/devices', f'/admin/devices/{dev.id}'):
                assert key not in text(client.get(url))
            assert all(key not in c.value for c in client._cookies.values())
        assert not any(key in r.getMessage() for r in caplog.records)
        assert telemetry(app.test_client(), key, {'readings': [{'sensor_type': 'water_level', 'value': 1.0,
                                                                'unit': 'm'}]}).status_code == 201

    def test_plaintext_key_not_persisted(self, client, world):
        login(client, 'root')
        register(client, world)
        key = shown_key(text(client.get(f'/admin/devices/{device().id}')))
        dump = '\n'.join(db.session.connection().connection.driver_connection.iterdump())
        assert key and key not in dump and IoTDevice.hash_api_key(key) in dump

    def test_registration_is_audited(self, client, world):
        login(client, 'root')
        register(client, world)
        entry = AuditLog.query.filter_by(action='REGISTERED_DEVICE').one()
        dev = device()
        assert entry.success and entry.target_type == 'device' and entry.target_id == str(dev.id)
        assert 'Kathmandu' in entry.summary and 'Bagmati River' in entry.summary
        assert dev.api_key_hash not in entry.summary
        assert 'REGISTERED_DEVICE' in text(client.get(f'/admin/devices/{dev.id}'))  # device history

    @pytest.mark.parametrize('over, message', [
        ({'district_id': '9999'}, 'Select a valid district'),
        ({'district_id': ''}, 'Select a valid district'),
        ({'district_id': 'abc'}, 'Invalid district_id'),
        ({'river_id': 'bagmati_ltp'}, 'does not belong'),
        ({'river_id': '9999'}, 'Unknown river'),
        ({'river_id': ''}, 'needs an explicit river'),
        ({'latitude': ''}, 'given together'),
        ({'longitude': ''}, 'given together'),
        ({'latitude': '95'}, 'given together'),
        ({'latitude': 'nan'}, 'given together'),
        ({'device_id': 'bad id:x'}, 'Device ID must be'),
        ({'name': '  '}, 'Name is required'),
        ({'monitoring': 'nuclear'}, 'Choose what the device monitors'),
    ])
    def test_invalid_registration_refused_and_audited(self, client, world, over, message):
        login(client, 'root')
        over = {k: str(world[v]) if v in world else v for k, v in over.items()}
        response = register(client, world, **over)
        assert response.status_code == 400 and message in text(response)
        assert IoTDevice.query.count() == 0
        entry = AuditLog.query.filter_by(action='REGISTERED_DEVICE').one()
        assert not entry.success and entry.target_id == 'new' and message in entry.summary

    def test_missing_reason_refused(self, client, world):
        login(client, 'root')
        assert register(client, world, reason='  ').status_code == 400
        assert device() is None

    def test_duplicate_device_id_rejected(self, client, world):
        login(client, 'root')
        register(client, world)
        original = device()
        response = register(client, world, district_id=str(world['ltp']), river_id=str(world['bagmati_ltp']))
        assert response.status_code == 400 and 'already exists' in text(response)
        assert IoTDevice.query.count() == 1 and device().district_id == original.district_id

    def test_other_monitoring_may_omit_river(self, client, world):
        login(client, 'root')
        assert register(client, world, monitoring='other', river_id='', latitude='', longitude='').status_code == 302
        dev = device()
        assert dev.river_id is None and dev.latitude is None and dev.district_id == world['ktm']

    def test_unknown_fields_are_not_mass_assigned(self, client, world):
        login(client, 'root')
        register(client, world, api_key_hash='attacker', enabled='0', status='decommissioned', authority_id='1',
                 id='77', last_seen='2020-01-01')
        dev = device()
        assert dev.id != 77 and dev.api_key_hash != 'attacker' and dev.enabled and dev.status == 'active'
        assert dev.authority_id is None and dev.last_seen is None


class TestTelemetryUsesRegisteredLocation:
    def _registered(self, client, world):
        login(client, 'root')
        register(client, world)
        return shown_key(text(client.get(f'/admin/devices/{device().id}')))

    def test_reading_resolves_to_registered_district_and_river(self, app, client, world):
        key = self._registered(client, world)
        # the payload tries to claim another district/river/device: all ignored
        payload = {'district_id': world['ltp'], 'district': 'Lalitpur', 'river_id': world['bagmati_ltp'],
                   'device_id': 'SOMETHING-ELSE',
                   'readings': [{'sensor_type': 'water_level', 'value': 4.2, 'unit': 'm',
                                 'district_id': world['ltp']}]}
        assert telemetry(app.test_client(), key, payload).status_code == 201
        dev = device()
        assert (dev.district_id, dev.river_id) == (world['ktm'], world['bagmati'])
        assert db.session.get(River, world['bagmati']).current_level == 4.2
        assert db.session.get(River, world['bagmati_ltp']).current_level is None
        assert db.session.get(River, world['bishnumati']).current_level is None  # no .first() guess

        event = Incident.query.filter_by(event_type='flood').one()
        assert (event.district_id, event.river_id) == (world['ktm'], world['bagmati'])
        notified = {n.user_id for n in Notification.query.filter_by(incident_id=event.id)}
        users = {u.username: u.id for u in User.query}
        assert {users['cit_k'], users['auth_k'], users['root']} <= notified
        assert users['cit_l'] not in notified


class TestEdit:
    def _edit(self, client, pk, **data):
        base = {'status': 'active', 'river_id': '', 'firmware_version': '', 'location_description': '',
                'latitude': '', 'longitude': '', 'reason': 'maintenance'}
        base.update(data)
        return client.post(f'/admin/devices/{pk}/edit', data=base)

    def test_edit_allowed_fields_and_audit(self, client, world):
        login(client, 'root')
        register(client, world)
        pk = device().id
        response = self._edit(client, pk, status='maintenance', river_id=str(world['bishnumati']),
                              firmware_version='1.1.0', latitude='27.71', longitude='85.31',
                              district_id=str(world['ltp']), device_id='HIJACK', api_key_hash='x')
        assert response.status_code == 302
        dev = device()
        assert (dev.status, dev.river_id, dev.firmware_version, dev.latitude) == ('maintenance', world['bishnumati'],
                                                                                 '1.1.0', 27.71)
        assert dev.district_id == world['ktm'] and dev.device_id == 'ESP32-FLOOD-001' and dev.api_key_hash != 'x'
        assert AuditLog.query.filter_by(action='UPDATED_DEVICE', success=True).count() == 1

    @pytest.mark.parametrize('data, message', [
        ({'river_id': 'bagmati_ltp'}, 'does not belong'),
        ({'river_id': ''}, 'not removed'),
        ({'latitude': '27.7'}, 'given together'),
        ({'status': 'exploded'}, 'Status must be one of'),
    ])
    def test_edit_refusals(self, client, world, data, message):
        login(client, 'root')
        register(client, world)
        pk = device().id
        data = {k: str(world[v]) if v in world else v for k, v in data.items()}
        data.setdefault('river_id', str(world['bagmati']))
        self._edit(client, pk, **data)
        dev = device()
        assert dev.river_id == world['bagmati'] and dev.status == 'active'
        entry = AuditLog.query.filter_by(action='UPDATED_DEVICE').one()
        assert not entry.success and message in entry.summary

    @pytest.mark.parametrize('who', ['cit_k', 'auth_k'])
    def test_edit_refused_for_non_admins(self, client, world, who):
        login(client, 'root')
        register(client, world)
        pk = device().id
        login(client, who)
        assert self._edit(client, pk, status='decommissioned').status_code == 403
        assert device().status == 'active'
