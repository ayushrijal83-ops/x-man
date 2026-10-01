"""Product-quality milestone: account contact/address/location data, auth UX, citizen and
authority dashboards built from real data, the district-selection fix, images and privacy."""
import os

import pytest

from app.extensions import db
from app.image_credits import IMAGE_CREDITS
from app.models import (Authority, CitizenReport, District, Incident, IncidentResponseAction, IoTDevice, Project,
                        River, RoadSegment, User)
from app.services.account_service import AccountError, normalize_mobile, parse_coordinates
from app.services.hazard_event_service import add_affected_district, create_hazard_event

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def world(app):
    with app.app_context():
        a, b, c = (District(name=n, province='Bagmati', headquarters=n + ' HQ') for n in ('Alpha', 'Beta', 'Gamma'))
        db.session.add_all([a, b, c])
        db.session.commit()
        auth_a = Authority(name='Alpha Office', category='roads', district_id=a.id)
        auth_b = Authority(name='Beta Office', category='roads', district_id=b.id)
        db.session.add_all([auth_a, auth_b])
        db.session.commit()
        users = {}
        for i, (name, role, district, authority) in enumerate([
                ('cit_a', 'citizen', a, None), ('cit_b', 'citizen', b, None), ('cit_none', 'citizen', None, None),
                ('auth_a', 'authority', a, auth_a), ('auth_b', 'authority', b, auth_b),
                ('auth_unlinked', 'authority', a, None), ('admin', 'admin', None, None)]):
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district.id if district else None,
                        authority_id=authority.id if authority else None, phone=f'+97798110000{i:02d}',
                        full_name=f'Full {name}', permanent_address=f'Ward {i}, {name} street',
                        current_latitude=27.0 + i / 100, current_longitude=85.0 + i / 100)
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'c': c.id, 'auth_a': auth_a.id, 'auth_b': auth_b.id,
                'u': {k: v.id for k, v in users.items()}}


def login(client, username, password='pw'):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('cit') else '/auth/authority/login'
    return client.post(path, data={'username': username, 'password': password})


def page(client, url):
    client.get('/language/set/en')
    response = client.get(url)
    return response.status_code, response.get_data(as_text=True)


REG = {'full_name': 'Sita Rai', 'username': 'sita', 'email': 'Sita@Example.np', 'mobile': '984-123 4567',
       'password': 'long-enough-pw', 'confirm_password': 'long-enough-pw', 'permanent_address': 'Ward 4, Kamalamai'}


def register(client, world, **overrides):
    data = {**REG, 'district_id': str(world['a']), **overrides}
    return client.post('/auth/register', data={k: v for k, v in data.items() if v is not None})


# ============================================================================ mobile + coordinates

@pytest.mark.parametrize('raw, expected', [
    ('9841234567', '+9779841234567'), ('984-123 4567', '+9779841234567'), ('+977 9801234567', '+9779801234567'),
    ('977-9621234567', '+9779621234567'), ('00977 9741234567', '+9779741234567'), ('(984) 123-4567', '+9779841234567'),
    ('+44 20 7946 0958', '+442079460958'), ('+1 (415) 555-0100', '+14155550100'),
])
def test_mobile_normalized_to_e164(raw, expected):
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize('raw', ['', '   ', None, 123, '12345', '9941234567', '+9779941234567', '98412345678',
                                 '984123456', '+977 98412', '98ab123456', '+1234567', '+1234567890123456', '0461-520123'])
def test_mobile_rejected(raw):
    with pytest.raises(AccountError):
        normalize_mobile(raw)


@pytest.mark.parametrize('lat, lon', [('nan', '85'), ('27', 'inf'), ('91', '85'), ('27', '-181'), ('27', ''),
                                      ('', '85'), ('abc', '85'), ('1e999', '85')])
def test_coordinates_validated(lat, lon):
    with pytest.raises(AccountError):
        parse_coordinates(lat, lon)


def test_coordinates_accepted():
    assert parse_coordinates('27.7172', '85.3240') == (27.7172, 85.324)
    assert parse_coordinates('', '') == (None, None) and parse_coordinates(None, None) == (None, None)


# ============================================================================ registration

class TestRegistration:
    def test_persists_contact_address_and_location(self, app, client, world):
        response = register(client, world, current_latitude='27.21', current_longitude='85.91',
                            current_address='Near the bus park')
        assert response.status_code == 302 and response.headers['Location'].endswith('/auth/login')
        with app.app_context():
            user = User.query.filter_by(username='sita').one()
            assert (user.email, user.phone, user.phone_verified) == ('sita@example.np', '+9779841234567', False)
            assert (user.full_name, user.permanent_address, user.district_id) == ('Sita Rai', 'Ward 4, Kamalamai', world['a'])
            assert (user.current_latitude, user.current_longitude, user.current_address) == (27.21, 85.91, 'Near the bus park')
            assert user.location_updated_at is not None and user.role == 'citizen'

    def test_location_is_optional_and_never_invented(self, app, client, world):
        assert register(client, world, current_address='typed but no GPS').status_code == 302
        with app.app_context():
            user = User.query.filter_by(username='sita').one()
            assert (user.current_latitude, user.current_longitude, user.current_address, user.location_updated_at) == \
                (None, None, None, None)

    @pytest.mark.parametrize('overrides, field', [
        ({'mobile': '12345'}, 'Nepal mobile'), ({'mobile': '+977 9811000000'}, 'already registered'),
        ({'mobile': ''}, 'Mobile number is required'), ({'password': 'short', 'confirm_password': 'short'}, 'at least 8'),
        ({'confirm_password': 'different-pw'}, 'do not match'), ({'district_id': '999'}, 'Choose your district'),
        ({'district_id': 'abc'}, 'Choose your district'), ({'permanent_address': ''}, 'Permanent address is required'),
        ({'permanent_address': 'x' * 301}, 'at most 300'), ({'full_name': ''}, 'Full name is required'),
        ({'username': 'a b'}, 'Username must'), ({'username': 'cit_a'}, 'already taken'),
        ({'email': 'CIT_A@T.NP'}, 'already registered'), ({'email': 'not-an-email'}, 'valid email'),
        ({'current_latitude': 'nan', 'current_longitude': '85'}, 'out of range'),
        ({'current_latitude': '27'}, 'provided together'), ({'current_latitude': '95', 'current_longitude': '85'}, 'out of range'),
    ])
    def test_invalid_input_rejected_without_creating_user(self, app, client, world, overrides, field):
        client.get('/language/set/en')
        response = register(client, world, **overrides)
        assert response.status_code == 400 and field in response.get_data(as_text=True)
        with app.app_context():
            assert User.query.filter_by(username=overrides.get('username', 'sita')).count() == \
                (1 if overrides.get('username') == 'cit_a' else 0)

    def test_values_kept_but_password_never_echoed(self, client, world):
        client.get('/language/set/en')
        body = register(client, world, mobile='bad', password='secret-password-1',
                        confirm_password='secret-password-1').get_data(as_text=True)
        assert 'Ward 4, Kamalamai' in body and 'Sita Rai' in body
        assert 'secret-password-1' not in body
        assert 'aria-invalid="true"' in body

    def test_register_page_has_explicit_location_control(self, client, world):
        status, body = page(client, '/auth/register')
        assert status == 200 and 'Use my current location' in body and 'data-locate' in body
        assert 'getCurrentPosition' in body and 'PERMISSION_DENIED' in body
        script = body.split('getCurrentPosition')[0]
        assert "addEventListener('click'" in script  # only on an explicit click, never on load


class TestLogin:
    def test_same_error_for_unknown_user_and_wrong_password(self, client, world):
        client.get('/language/set/en')
        for user, pw in (('cit_a', 'wrong'), ('nobody', 'pw')):
            response = client.post('/auth/login', data={'username': user, 'password': pw})
            assert response.status_code == 401 and 'Invalid username or password.' in response.get_data(as_text=True)

    def test_login_still_redirects_safely(self, client, world):
        response = client.post('/auth/login?next=https://evil.example', data={'username': 'cit_a', 'password': 'pw'})
        assert response.status_code == 302 and 'evil' not in response.headers['Location']

    def test_pages_render_with_csrf_fields(self, client, world):
        for url in ('/auth/login', '/auth/register', '/auth/authority/login'):
            status, body = page(client, url)
            assert status == 200 and 'name="csrf_token"' in body and 'skip-link' in body


# ============================================================================ profile + privacy

class TestProfile:
    def test_update_normalizes_phone_and_resets_verification(self, app, client, world):
        with app.app_context():
            user = db.session.get(User, world['u']['cit_a'])
            user.phone_verified = True
            db.session.commit()
        login(client, 'cit_a')
        assert client.post('/profile/edit', data={'phone': '9851112222'}).status_code == 302
        with app.app_context():
            user = db.session.get(User, world['u']['cit_a'])
            assert (user.phone, user.phone_verified) == ('+9779851112222', False)
            assert user.permanent_address == 'Ward 0, cit_a street'  # untouched: field not submitted

    def test_duplicate_phone_rejected(self, app, client, world):
        login(client, 'cit_a')
        client.get('/language/set/en')
        response = client.post('/profile/edit', data={'phone': '+977 98110000 01'})  # cit_b's number
        assert response.status_code == 400 and 'already registered' in response.get_data(as_text=True)

    def test_location_update_and_clear_never_touch_permanent_address(self, app, client, world):
        login(client, 'cit_a')
        client.post('/profile/edit', data={'current_latitude': '26.5', 'current_longitude': '87.3',
                                           'current_address': 'Relief camp'})
        with app.app_context():
            user = db.session.get(User, world['u']['cit_a'])
            assert (user.current_latitude, user.current_longitude, user.current_address) == (26.5, 87.3, 'Relief camp')
            assert user.permanent_address == 'Ward 0, cit_a street'
        client.post('/profile/edit', data={'clear_location': '1'})
        with app.app_context():
            user = db.session.get(User, world['u']['cit_a'])
            assert (user.current_latitude, user.current_longitude, user.location_updated_at) == (None, None, None)
            assert user.permanent_address == 'Ward 0, cit_a street'

    @pytest.mark.parametrize('data', [{'current_latitude': 'nan', 'current_longitude': '1'},
                                      {'current_latitude': '1', 'current_longitude': '200'}])
    def test_bad_location_rejected(self, app, client, world, data):
        login(client, 'cit_a')
        assert client.post('/profile/edit', data=data).status_code == 400
        with app.app_context():
            assert db.session.get(User, world['u']['cit_a']).current_latitude == 27.0

    def test_private_fields_only_for_owner_and_admin(self, client, world):
        url = f"/profile/{world['u']['cit_a']}"
        secrets = ('+97798110000', 'Ward 0, cit_a street', 'Full cit_a', '27.00000')
        login(client, 'cit_b')
        _, body = page(client, url)
        assert not any(s in body for s in secrets)
        login(client, 'cit_a')
        _, body = page(client, url)
        assert all(s in body for s in secrets)
        # M12: admins see contact/address, but only that a location was shared, not the coordinates
        login(client, 'admin')
        _, body = page(client, url)
        assert all(s in body for s in secrets[:3]) and '27.00000' not in body and 'Current location shared' in body

    def test_private_fields_never_in_apis(self, app, client, world):
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'])
        for who in ('cit_b', 'auth_a', 'admin'):
            login(client, who)
            for url in ('/api/dashboard', '/api/hazards', '/api/notifications', '/api/reports'):
                body = client.get(url).get_data(as_text=True)
                for secret in ('+97798110000', 'cit_a street', 'current_latitude', 'permanent_address', 'phone'):
                    assert secret not in body, (who, url, secret)


# ============================================================================ citizen dashboard

class TestCitizenDashboard:
    def test_real_counts_and_own_data_only(self, app, client, world):
        with app.app_context():
            create_hazard_event('flood', 'high', 'authority', district_id=world['a'], title='Alpha flood',
                                latitude=27.1, longitude=85.1)
            beta = create_hazard_event('landslide', 'medium', 'authority', district_id=world['b'], title='Beta slide')
            add_affected_district(beta, world['a'])  # M04: also affects Alpha
            create_hazard_event('road_damage', 'low', 'authority', district_id=world['c'], title='Gamma crack')
            for user, district in (('cit_a', 'a'), ('cit_b', 'b')):
                db.session.add(CitizenReport(reporter_id=world['u'][user], district_id=world[district],
                                             hazard_type='landslide', image_filename=f'{"0" * 31}{len(user)}{user[-1]}.jpg'[-36:],
                                             status='submitted', location=f'{user} landmark'))
            db.session.commit()
        login(client, 'cit_a')
        status, body = page(client, '/dashboard')
        assert status == 200
        assert 'Alpha flood' in body and 'Beta slide' in body and 'Gamma crack' not in body
        assert 'Nationwide active hazards: <strong>3</strong>' in body
        assert 'cit_a landmark' in body and 'cit_b landmark' not in body
        assert '"lat": 27.1' in body  # only the hazard with real coordinates is mapped
        assert 'source_reference' not in body

    def test_zero_data_states(self, client, world):
        login(client, 'cit_a')
        _, body = page(client, '/dashboard')
        assert 'No active hazards in your district right now.' in body
        assert 'You have not sent any reports yet.' in body and 'No alerts yet.' in body
        assert 'No hazard here has map coordinates yet.' in body

    def test_no_district_prompts_and_selection_persists(self, app, client, world):
        login(client, 'cit_none')
        _, body = page(client, '/dashboard')
        assert 'Set your district' in body and 'action="/select-district"' in body
        response = client.post('/select-district', data={'district_id': str(world['b']), 'next': f"/district/{world['b']}"})
        assert response.status_code == 302 and response.headers['Location'].endswith(f"/district/{world['b']}")
        with app.app_context():
            assert db.session.get(User, world['u']['cit_none']).district_id == world['b']
        _, body = page(client, '/dashboard')
        assert 'Beta' in body and 'Set your district' not in body

    @pytest.mark.parametrize('value', ['abc', '999', '', '1;DROP'])
    def test_invalid_selection_ignored(self, app, client, world, value):
        login(client, 'cit_a')
        response = client.post('/select-district', data={'district_id': value, 'next': 'https://evil.example'})
        assert response.status_code == 302 and response.headers['Location'].endswith('/dashboard')
        with app.app_context():
            assert db.session.get(User, world['u']['cit_a']).district_id == world['a']


# ============================================================================ district pages

class TestDistrictPages:
    def test_district_with_data(self, app, client, world):
        with app.app_context():
            db.session.add_all([River(name='Alpha River', district_id=world['a'], current_level=3.3, danger_level=4.0,
                                      status='rising'),
                                Project(name='Alpha Bridge', district_id=world['a'], progress_percent=40)])
            for i in range(15):  # more than the 12 listed: the total must still be the real count
                db.session.add(RoadSegment(name=f'Alpha Road {i}', district_id=world['a'], status='blocked' if i < 3 else 'open'))
            db.session.commit()
            create_hazard_event('flood', 'critical', 'authority', district_id=world['a'], title='Alpha critical flood')
        login(client, 'cit_b')
        status, body = page(client, f"/district/{world['a']}")
        assert status == 200
        for text in ('Alpha River', 'Alpha Bridge', 'Alpha Office', 'Alpha critical flood', 'Alpha Road 0',
                     '<div class="stat-value">15</div>', 'blocked 3', 'open 12', 'Set as my district'):
            assert text in body, text
        assert 'Alpha Road 9' not in body  # list is capped at 12 (name order: 0,1,10..14,2..6), count is not

    def test_empty_district_and_unknown_id(self, client, world):
        login(client, 'cit_a')
        status, body = page(client, f"/district/{world['c']}")
        assert status == 200 and 'No active hazards in this district.' in body
        assert 'No rivers recorded for this district.' in body
        assert page(client, '/district/99999')[0] == 404

    def test_public_page_shows_no_private_report_data(self, app, client, world):
        with app.app_context():
            event = create_hazard_event('landslide', 'medium', 'citizen_report', district_id=world['a'],
                                        source_reference='report_42')
            db.session.add(CitizenReport(reporter_id=world['u']['cit_a'], district_id=world['a'], hazard_type='landslide',
                                         incident_id=event.id, image_filename='a' * 32 + '.jpg', status='submitted',
                                         description='PRIVATE-REPORT-TEXT'))
            db.session.commit()
        login(client, 'cit_b')
        _, body = page(client, f"/district/{world['a']}")
        assert 'PRIVATE-REPORT-TEXT' not in body and 'report_42' not in body and 'a' * 32 not in body

    def test_district_list_marks_own_and_status_filters_tolerate_bad_ids(self, client, world):
        login(client, 'cit_a')
        _, body = page(client, '/districts')
        assert 'Your district' in body and 'Find a district' in body
        for url in ('/roads/status?district_id=abc', '/rivers/status?district_id=1;DROP'):
            assert client.get(url).status_code == 200


# ============================================================================ authority dashboard

class TestAuthorityDashboard:
    def test_scoped_operational_data(self, app, client, world):
        with app.app_context():
            a_event = create_hazard_event('flood', 'high', 'authority', district_id=world['a'], title='Alpha flood ops')
            create_hazard_event('flood', 'high', 'authority', district_id=world['b'], title='Beta flood ops')
            db.session.add_all([
                IoTDevice(device_id='DEV-A', name='Alpha gauge', district_id=world['a'], authority_id=world['auth_a'],
                          api_key_hash=IoTDevice.hash_api_key('ka'), enabled=True),
                IoTDevice(device_id='DEV-B', name='Beta gauge', district_id=world['b'], authority_id=world['auth_b'],
                          api_key_hash=IoTDevice.hash_api_key('kb'), enabled=True),
                IncidentResponseAction(incident_id=a_event.id, author_id=world['u']['auth_a'], action_type='close_road',
                                       description='Close Alpha road', status='in_progress'),
                CitizenReport(reporter_id=world['u']['cit_a'], district_id=world['a'], hazard_type='landslide',
                              image_filename='b' * 32 + '.jpg', status='submitted', description='PRIVATE-A',
                              ai_status='completed', ai_label='landslide', ai_confidence=0.91, ai_model='m'),
                CitizenReport(reporter_id=world['u']['cit_b'], district_id=world['b'], hazard_type='landslide',
                              image_filename='c' * 32 + '.jpg', status='submitted'),
            ])
            db.session.commit()
        login(client, 'auth_a')
        status, body = page(client, '/authority/dashboard')
        assert status == 200
        for text in ('Alpha flood ops', 'Alpha gauge', 'Close Alpha road', 'Landslide · Model confidence 0.91', 'Alpha Office'):
            assert text in body, text
        for text in ('Beta flood ops', 'Beta gauge', 'PRIVATE-A', IoTDevice.hash_api_key('ka'), 'api_key'):
            assert text not in body, text
        assert '<div class="stat-value">1</div><div class="stat-label">Photo reports to review' in body.replace('\n', '')

    def test_admin_goes_to_system_console_and_others_are_turned_away(self, client, world):
        login(client, 'admin')
        response = client.get('/authority/dashboard')
        assert response.status_code == 302 and response.headers['Location'].endswith('/monitoring')
        for who in ('auth_unlinked', 'cit_a'):
            login(client, who)
            response = client.get('/authority/dashboard')
            assert response.status_code == 302 and response.headers['Location'].endswith('/dashboard')

    def test_panel_pages_share_navigation(self, client, world):
        login(client, 'auth_a')
        for url in ('/authority/complaints', '/authority/projects', '/authority/roads', '/authority/rivers'):
            status, body = page(client, url)
            assert status == 200 and 'aria-label="Authority panel"' in body and 'Alpha Office' in body


# ============================================================================ landing, images, design system

class TestPublicPagesAndImages:
    def test_landing_uses_counted_stats(self, client, world):
        status, body = page(client, '/')
        assert status == 200
        assert '<div class="lp-stat-value">3</div><div class="lp-stat-label">Districts covered' in body.replace('\n', '').replace('            ', '')
        assert '24/7' not in body and 'Example alert' in body

    def test_every_credited_image_exists_and_is_attributed(self, client, world):
        _, body = page(client, '/credits')
        for name, credit in IMAGE_CREDITS.items():
            path = os.path.join(REPO, 'app', 'static', 'images', name)
            assert os.path.isfile(path) and os.path.getsize(path) < 400_000, name
            assert credit['license'].startswith(('CC BY', 'CC0')) and credit['source'].startswith('https://commons.wikimedia.org/')
            assert f'/static/images/{name}' in body and credit['author'] in body

    def test_design_system_loaded_with_accessibility_basics(self, client, world):
        _, body = page(client, '/auth/login')
        assert '/static/css/xman.css' in body and 'class="skip-link"' in body
        css = open(os.path.join(REPO, 'app', 'static', 'css', 'xman.css'), encoding='utf-8').read()
        for rule in ('prefers-reduced-motion', ':focus-visible', '.sev-critical', '.sev-normal', 'prefers-reduced-transparency'):
            assert rule in css
