"""M05: mobile citizen photo reports — validation, upload security, incident/notification integration, RBAC, UI."""
import io
import os
import re

import pytest
from PIL import Image

from app.extensions import db
from app.models import Authority, CitizenReport, District, Incident, Notification, User
from app.models.incident import HAZARD_TYPES
from app.services.hazard_event_service import create_hazard_event


@pytest.fixture(autouse=True)
def upload_dir(app, tmp_path):
    path = tmp_path / 'reports'
    app.config['REPORT_UPLOAD_DIR'] = str(path)
    return path


@pytest.fixture
def world(app):
    with app.app_context():
        a = District(name='District A', province='P')
        b = District(name='District B', province='P')
        db.session.add_all([a, b])
        db.session.commit()
        auth_a = Authority(name='Auth A', category='roads', district_id=a.id)
        auth_b = Authority(name='Auth B', category='roads', district_id=b.id)
        db.session.add_all([auth_a, auth_b])
        db.session.commit()
        users = {}
        for username, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None),
            ('citizen_a2', 'citizen', a.id, None),
            ('citizen_b', 'citizen', b.id, None),
            ('auth_a', 'authority', a.id, auth_a.id),
            ('auth_b', 'authority', b.id, auth_b.id),
            ('admin', 'admin', None, None),
        ]:
            user = User(username=username, email=f'{username}@t.np', role=role,
                        district_id=district_id, authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[username] = user
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'u': {k: v.id for k, v in users.items()}}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _image(fmt='JPEG', size=(64, 48), exif=None):
    buf = io.BytesIO()
    kwargs = {'exif': exif} if exif is not None else {}
    Image.new('RGB', size, (120, 90, 60)).save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _post(client, world, image=None, filename='photo.jpg', mimetype='image/jpeg', **fields):
    data = {'hazard_type': 'road_damage', 'district_id': str(world['a']),
            'latitude': '27.2', 'longitude': '85.9'}
    data.update({k: v for k, v in fields.items() if v is not None})
    for k in [k for k, v in fields.items() if v is None]:
        data.pop(k, None)
    if image is not False:
        data['image'] = (io.BytesIO(_image() if image is None else image), filename, mimetype)
    return client.post('/api/reports', data=data, content_type='multipart/form-data')


class TestSubmission:
    @pytest.mark.parametrize('hazard', ['landslide', 'road_damage'])
    def test_report_creates_detected_citizen_incident(self, app, client, world, upload_dir, hazard):
        _login(client, 'citizen_a')
        response = _post(client, world, hazard_type=hazard, description='  Crack across the road  ',
                         location='near the bridge')
        assert response.status_code == 201
        body = response.get_json()
        report = body['report']
        assert body['incident_created'] is True
        assert report['status'] == 'submitted'
        assert report['hazard_type'] == hazard
        assert report['district'] == {'id': world['a'], 'name': 'District A'}
        assert report['description'] == 'Crack across the road'
        assert report['image_url'] == f"/api/reports/{report['id']}/image"
        text = str(body)
        assert 'image_filename' not in text and 'uploads' not in text and 'source_reference' not in text
        assert 'reporter' not in report  # citizens don't get reporter identity

        with app.app_context():
            incident = db.session.get(Incident, report['incident_id'])
            assert (incident.event_type, incident.source, incident.status, incident.severity) == \
                (hazard, 'citizen_report', 'detected', 'medium')
            assert incident.source_reference == f"report_{report['id']}"
            assert incident.location == 'near the bridge'
            assert 'Crack' not in (incident.description or '')  # private text stays on the report
            stored = db.session.get(CitizenReport, report['id']).image_filename
        assert re.fullmatch(r'[0-9a-f]{32}\.jpg', stored)
        assert os.listdir(upload_dir) == [stored]

    @pytest.mark.parametrize('hazard', ['earthquake', 'flood', 'iot', 'authority', '', 'LANDSLIDE'])
    def test_non_visual_hazard_types_rejected(self, client, world, hazard):
        _login(client, 'citizen_a')
        response = _post(client, world, hazard_type=hazard)
        assert response.status_code == 400
        assert 'hazard_type' in response.get_json()['error']

    def test_global_hazard_types_unchanged(self):
        assert HAZARD_TYPES == ['flood', 'earthquake', 'landslide', 'road_damage']

    def test_client_cannot_choose_source_status_severity_or_incident(self, app, client, world):
        with app.app_context():
            other = create_hazard_event('flood', 'low', 'authority', district_id=world['b'])
            other_id = other.id
        _login(client, 'citizen_a')
        response = _post(client, world, source='iot', status='accepted', severity='critical',
                         incident_id=str(other_id), reporter_id=str(world['u']['admin']))
        assert response.status_code == 201
        report = response.get_json()['report']
        assert report['status'] == 'submitted'
        assert report['incident_id'] != other_id
        with app.app_context():
            incident = db.session.get(Incident, report['incident_id'])
            assert (incident.source, incident.severity) == ('citizen_report', 'medium')
            assert db.session.get(CitizenReport, report['id']).reporter_id == world['u']['citizen_a']

    def test_gps_optional_manual_fallback(self, app, client, world):
        _login(client, 'citizen_a')
        response = _post(client, world, latitude=None, longitude=None, location='Kamalamai market')
        assert response.status_code == 201
        assert response.get_json()['report']['latitude'] is None

    @pytest.mark.parametrize('lat,lon', [('abc', '85'), ('nan', '85'), ('inf', '85'), ('91', '85'),
                                         ('27', '-181'), ('27', ''), ('', '85'), ('1e999', '85')])
    def test_invalid_coordinates(self, client, world, lat, lon):
        _login(client, 'citizen_a')
        assert _post(client, world, latitude=lat, longitude=lon).status_code == 400

    def test_district_validation(self, client, world):
        _login(client, 'citizen_a')
        assert _post(client, world, district_id=None).status_code == 400
        assert _post(client, world, district_id='abc').status_code == 400
        assert _post(client, world, district_id='1 OR 1=1').status_code == 400
        assert _post(client, world, district_id='99999').status_code == 404

    def test_text_limits(self, client, world):
        _login(client, 'citizen_a')
        assert _post(client, world, description='x' * 1001).status_code == 400
        assert _post(client, world, location='x' * 201).status_code == 400
        response = _post(client, world, description='   ')
        assert response.status_code == 201
        assert response.get_json()['report']['description'] is None


class TestUploadSecurity:
    def test_missing_image(self, client, world, upload_dir):
        _login(client, 'citizen_a')
        assert _post(client, world, image=False).status_code == 400
        assert _post(client, world, filename='').status_code == 400
        assert not upload_dir.exists() or os.listdir(upload_dir) == []

    @pytest.mark.parametrize('payload,filename,mimetype', [
        (b'MZ\x90\x00 fake exe', 'evil.exe', 'application/octet-stream'),
        (b'<?php system($_GET["c"]); ?>', 'shell.php.jpg', 'image/jpeg'),
        (b'not an image at all', 'photo.jpg', 'image/jpeg'),
        (b'%PDF-1.4 doc', 'doc.pdf', 'application/pdf'),
        (b'', 'empty.jpg', 'image/jpeg'),
        ('SVG', 'vector.svg', 'image/svg+xml'),
        ('GIF', 'anim.gif', 'image/gif'),
        ('PNG', 'photo.jpg', 'image/jpeg'),  # content/extension mismatch
        ('JPEG', 'photo.png', 'image/png'),
        ('JPEG', 'photo.jpg', 'text/plain'),  # non-image MIME
        ('JPEG', 'noextension', 'image/jpeg'),
    ])
    def test_rejects_bad_files(self, client, world, upload_dir, payload, filename, mimetype):
        if payload == 'SVG':
            payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        elif isinstance(payload, str):
            payload = _image(payload)
        _login(client, 'citizen_a')
        response = _post(client, world, image=payload, filename=filename, mimetype=mimetype)
        assert response.status_code == 400, response.get_json()
        assert not upload_dir.exists() or os.listdir(upload_dir) == []

    @pytest.mark.parametrize('fmt,name', [('PNG', 'a.png'), ('WEBP', 'a.webp'), ('JPEG', 'a.JPEG')])
    def test_accepts_png_webp_and_uppercase_extension(self, client, world, fmt, name):
        _login(client, 'citizen_a')
        assert _post(client, world, image=_image(fmt), filename=name, mimetype='image/' + fmt.lower()).status_code == 201

    def test_oversized_upload(self, client, world):
        _login(client, 'citizen_a')
        response = _post(client, world, image=b'\xff\xd8' + b'0' * (10 * 1024 * 1024))
        assert response.status_code == 413
        big = _post(client, world, image=b'0' * (17 * 1024 * 1024))  # over app-wide MAX_CONTENT_LENGTH
        assert big.status_code == 413
        assert 'error' in big.get_json()

    def test_decompression_bomb_rejected(self, client, world):
        buf = io.BytesIO()
        Image.new('1', (10000, 10000)).save(buf, format='PNG')  # tiny file, 100 MP
        _login(client, 'citizen_a')
        response = _post(client, world, image=buf.getvalue(), filename='bomb.png', mimetype='image/png')
        assert response.status_code == 400
        assert 'too large' in response.get_json()['error']

    def test_path_traversal_filename_is_ignored(self, client, world, upload_dir, tmp_path):
        _login(client, 'citizen_a')
        assert _post(client, world, filename='../../evil.jpg').status_code == 201
        assert _post(client, world, filename='..\\..\\evil.jpg').status_code == 201
        assert not (tmp_path / 'evil.jpg').exists()
        assert all(re.fullmatch(r'[0-9a-f]{32}\.jpg', f) for f in os.listdir(upload_dir))

    def test_exif_and_embedded_gps_are_stripped_and_image_reencoded(self, client, world, upload_dir):
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'  # Make
        exif[0x8825] = {1: 'N', 2: (27.0, 42.0, 0.0)}  # GPS IFD
        big = _image(size=(4000, 3000), exif=exif.tobytes())
        _login(client, 'citizen_a')
        assert _post(client, world, image=big).status_code == 201
        stored = upload_dir / os.listdir(upload_dir)[0]
        with Image.open(stored) as img:
            assert img.format == 'JPEG'
            assert max(img.size) == 2560  # downscaled
            assert len(img.getexif()) == 0

    def test_malformed_requests(self, client, world):
        _login(client, 'citizen_a')
        assert client.post('/api/reports', json={'hazard_type': 'landslide'}).status_code == 400
        assert client.post('/api/reports', data='garbage', content_type='text/plain').status_code == 400
        broken = client.post('/api/reports', data=b'--x\r\nbroken', content_type='multipart/form-data; boundary=x')
        assert broken.status_code == 400

    def test_requires_login_and_csrf(self, app, client, world):
        assert _post(client, world).status_code == 401
        _login(client, 'citizen_a')
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            assert _post(client, world).status_code == 400
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


class TestIncidentAndNotifications:
    def test_two_reports_one_incident(self, app, client, world):
        _login(client, 'citizen_a')
        first = _post(client, world, latitude='27.2000', longitude='85.9000').get_json()
        _login(client, 'citizen_a2')
        second_response = _post(client, world, latitude='27.2050', longitude='85.9030')
        second = second_response.get_json()
        assert second['incident_created'] is False
        assert second['report']['incident_id'] == first['report']['incident_id']
        assert second['report']['id'] != first['report']['id']
        with app.app_context():
            incident = db.session.get(Incident, first['report']['incident_id'])
            assert incident.report_count == 2
            assert len(incident.citizen_reports) == 2
            assert Incident.query.count() == 1

    def test_report_never_escalates_or_confirms(self, app, client, world):
        with app.app_context():
            existing = create_hazard_event('road_damage', 'low', 'authority', district_id=world['a'])
            existing_id = existing.id
        _login(client, 'citizen_a')
        report = _post(client, world, latitude=None, longitude=None).get_json()['report']
        assert report['incident_id'] == existing_id
        with app.app_context():
            incident = db.session.get(Incident, existing_id)
            assert (incident.severity, incident.status) == ('low', 'detected')
            assert Notification.query.filter_by(type='hazard_escalated').count() == 0

    def test_alerts_go_to_district_not_as_alert_to_reporter(self, app, client, world):
        u = world['u']
        _login(client, 'citizen_a')
        report_id = _post(client, world).get_json()['report']['id']
        with app.app_context():
            def types(name):
                return sorted(n.type for n in Notification.query.filter_by(user_id=u[name]))
            assert types('citizen_a') == ['report_update']  # receipt only, not a hazard alert
            assert types('citizen_a2') == ['hazard_detected']
            assert types('auth_a') == ['hazard_detected']
            assert types('admin') == ['hazard_detected']
            assert types('citizen_b') == []
            receipt = Notification.query.filter_by(user_id=u['citizen_a']).one()
            assert receipt.incident_id is None and receipt.dedup_key == f'report:{report_id}:submitted'
            assert 'not a hazard alert' in receipt.message

    def test_repeated_reports_do_not_duplicate_alerts(self, app, client, world):
        u = world['u']
        for name in ('citizen_a', 'citizen_a2', 'citizen_a'):
            _login(client, name)
            assert _post(client, world).status_code == 201
        with app.app_context():
            assert Notification.query.filter_by(type='hazard_detected').count() == 3  # citizen_a2, auth_a, admin
            assert Notification.query.filter_by(user_id=u['citizen_a2'], type='hazard_detected').count() == 1
            assert Notification.query.filter_by(user_id=u['citizen_a'], type='report_update').count() == 2


class TestAccessAndReview:
    def _report(self, client, world, who='citizen_a'):
        _login(client, who)
        return _post(client, world).get_json()['report']['id']

    def test_ownership_and_visibility(self, client, world):
        rid = self._report(client, world)
        _login(client, 'citizen_b')
        assert client.get(f'/api/reports/{rid}').status_code == 404
        assert client.get(f'/api/reports/{rid}/image').status_code == 404
        assert client.get('/api/reports').get_json()['reports'] == []
        _login(client, 'auth_b')
        assert client.get(f'/api/reports/{rid}').status_code == 404
        assert client.get(f'/api/reports/{rid}/image').status_code == 404

        _login(client, 'citizen_a')
        assert [r['id'] for r in client.get('/api/reports').get_json()['reports']] == [rid]
        assert client.get('/api/reports/abc').status_code == 400
        assert client.get('/api/reports/99999').status_code == 404

        _login(client, 'auth_a')
        body = client.get(f'/api/reports/{rid}').get_json()['report']
        assert body['reporter'] == {'username': 'citizen_a'}
        assert 'email' not in str(body)
        _login(client, 'admin')
        assert client.get(f'/api/reports/{rid}').status_code == 200

    def test_image_served_privately(self, client, world):
        rid = self._report(client, world)
        response = client.get(f'/api/reports/{rid}/image')
        assert response.status_code == 200
        assert response.mimetype == 'image/jpeg'
        assert 'no-store' in response.headers['Cache-Control']
        assert Image.open(io.BytesIO(response.data)).format == 'JPEG'
        client.get('/auth/logout')
        assert client.get(f'/api/reports/{rid}/image').status_code == 401

    def test_no_public_static_copy(self, app, client, world):
        self._report(client, world)
        static_uploads = os.path.join(app.root_path, 'static', 'uploads')
        with app.app_context():
            name = CitizenReport.query.one().image_filename
        assert not os.path.exists(os.path.join(static_uploads, name))
        assert client.get(f'/static/uploads/{name}').status_code == 404

    def test_review_rules(self, app, client, world):
        rid = self._report(client, world)
        url = f'/api/reports/{rid}/review'
        assert client.post(url, json={'status': 'accepted'}).status_code == 403  # citizen
        _login(client, 'auth_b')
        assert client.post(url, json={'status': 'accepted'}).status_code == 404  # other district
        _login(client, 'auth_a')
        assert client.post(url, json={'status': 'confirmed'}).status_code == 400
        assert client.post(url, json=['accepted']).status_code == 400
        response = client.post(url, json={'status': 'accepted'})
        assert response.status_code == 200
        assert response.get_json()['report']['status'] == 'accepted'
        assert client.post(url, json={'status': 'rejected'}).status_code == 409
        with app.app_context():
            report = db.session.get(CitizenReport, rid)
            assert report.incident.status == 'detected'  # report review != incident lifecycle
            assert Notification.query.filter_by(user_id=world['u']['citizen_a'],
                                                dedup_key=f'report:{rid}:accepted').count() == 1

    def test_authority_cannot_review_own_report(self, client, world):
        rid = self._report(client, world, who='auth_a')
        assert client.post(f'/api/reports/{rid}/review', json={'status': 'accepted'}).status_code == 403
        _login(client, 'admin')
        assert client.post(f'/api/reports/{rid}/review', json={'status': 'rejected'}).status_code == 200

    def test_review_requires_csrf(self, app, client, world):
        rid = self._report(client, world)
        _login(client, 'admin')
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            assert client.post(f'/api/reports/{rid}/review', json={'status': 'accepted'}).status_code == 400
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


class TestPages:
    def test_report_page_is_mobile_camera_form(self, client, world):
        assert client.get('/report').status_code == 302
        _login(client, 'citizen_a')
        client.get('/language/set/en')
        body = client.get('/report').get_data(as_text=True)
        assert 'capture="environment"' in body
        assert 'accept="image/jpeg,image/png,image/webp"' in body
        assert 'value="landslide"' in body and 'value="road_damage"' in body
        assert 'earthquake' not in body
        assert 'Use My Location' in body and 'name="viewport"' in body
        client.get('/language/set/ne')
        assert 'जोखिम रिपोर्ट गर्नुहोस्' in client.get('/report').get_data(as_text=True)

    def test_my_reports_lists_only_own(self, client, world):
        _login(client, 'citizen_b')
        _post(client, world, district_id=str(world['b']), location='B-only place')
        _login(client, 'citizen_a')
        client.get('/language/set/en')
        _post(client, world, location='A place')
        body = client.get('/reports/mine').get_data(as_text=True)
        assert 'A place' in body and 'B-only place' not in body
        assert '/api/reports/' in body and 'submitted' in body
