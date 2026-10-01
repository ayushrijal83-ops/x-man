"""Final software QA (pre-hardware freeze): regression tests for every defect found in the full audit."""
import io
import json
import os
import re
import shutil
import subprocess

import pytest
from PIL import Image

from app.extensions import db
from app.models import (Authority, Comment, Complaint, District, Like, Notification, Post, PushSubscription, River,
                        RiverUpdate, User)
from app.services import notification_service, web_push
from app.services.hazard_event_service import create_hazard_event

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC, PRIVATE = web_push.generate_vapid_keys()


@pytest.fixture
def world(app):
    with app.app_context():
        a, b = District(name='Alpha', province='P'), District(name='Beta', province='P')
        db.session.add_all([a, b])
        db.session.commit()
        office = Authority(name='Alpha Office', category='roads', district_id=a.id)
        river = River(name='Kamala River', district_id=a.id, danger_level=5.0)
        db.session.add_all([office, river])
        db.session.commit()
        users = {}
        for name, role, lang in [('cit', 'citizen', 'en'), ('other', 'citizen', 'en'), ('nepali', 'citizen', 'ne'),
                                 ('auth', 'authority', 'en'), ('admin', 'admin', 'en')]:
            u = User(username=name, email=f'{name}@t.np', role=role, district_id=a.id, language=lang,
                     authority_id=office.id if role == 'authority' else None)
            u.set_password('pw')
            db.session.add(u)
            users[name] = u
        db.session.commit()
        return {'a': a.id, 'b': b.id, 'office': office.id, 'river': river.id,
                'u': {k: v.id for k, v in users.items()}}


def login(client, name):
    client.get('/auth/logout')
    client.post('/auth/login' if name in ('cit', 'other', 'nepali') else '/auth/authority/login',
                data={'username': name, 'password': 'pw'})
    client.get('/language/set/en')


def jpeg_with_exif():
    image = Image.new('RGB', (64, 48), (120, 160, 90))
    exif = Image.Exif()
    exif[0x010F] = 'SECRET-CAMERA'               # Make
    exif[0x8825] = {2: (27.0, 42.0, 0.0), 1: 'N'}  # GPS IFD: latitude
    buf = io.BytesIO()
    image.save(buf, 'JPEG', exif=exif)
    return buf.getvalue()


class TestServerErrorsFixed:
    """Each of these was a 500 found by the route crawler."""

    def test_dead_road_detail_route_is_gone(self, client, world):
        login(client, 'cit')
        assert client.get('/roads/1').status_code == 404  # template never existed; nothing linked to it

    @pytest.mark.parametrize('url', ['/authorities/directory?district_id=abc', '/projects/tracker?district_id=abc',
                                     '/social/feed?district_id=abc', '/social/hashtag/%25'])
    def test_junk_district_filters(self, client, world, url):
        login(client, 'cit')
        assert client.get(url).status_code == 200

    @pytest.mark.parametrize('url,field', [('/ai/classify', 'content'), ('/ai/generate', 'prompt'),
                                           ('/language/translate', 'text')])
    def test_non_object_json_bodies(self, client, world, url, field):
        login(client, 'cit')
        for body in ([1, 2, 3], 'text', 42, {field: 7}, {field: 'x' * 5000}):
            assert client.post(url, json=body).status_code == 400, body
        assert client.post(url, data='{bad', content_type='application/json').status_code == 400


class TestComplaints:
    def test_invalid_complaints_are_rejected_without_rows(self, app, client, world):
        login(client, 'cit')
        good = {'authority_id': world['office'], 'district_id': world['a'], 'category': 'road_blocked',
                'description': 'Pothole', 'urgency': 'medium'}
        for bad in ({'authority_id': 'abc'}, {'authority_id': '9999'}, {'district_id': 'x'}, {'district_id': '9999'},
                    {'category': ''}, {'category': 'bogus'}, {'urgency': 'apocalyptic'}, {'description': '  '},
                    {'description': 'x' * 5001}):
            assert client.post('/complaints/new', data={**good, **bad}).status_code == 302
        with app.app_context():
            assert Complaint.query.count() == 0
        client.post('/complaints/new', data=good)
        with app.app_context():
            complaint = Complaint.query.one()
            assert re.fullmatch(r'ALP-\d{4}-[0-9A-F]{6}', complaint.ticket_number)

    def test_ticket_numbers_never_collide(self, app, world, monkeypatch):
        from app.routes import complaints
        with app.app_context():
            district = db.session.get(District, world['a'])
            first = complaints.generate_ticket_number(district)
            db.session.add(Complaint(ticket_number=first, user_id=world['u']['cit'], authority_id=world['office'],
                                     district_id=district.id, category='other', description='x'))
            db.session.commit()
            tokens = iter([first.rsplit('-', 1)[1].lower(), 'abcdef'])
            monkeypatch.setattr(complaints.secrets, 'token_hex', lambda n: next(tokens))
            assert complaints.generate_ticket_number(district) != first

    def test_complaint_text_not_on_other_users_profiles(self, app, client, world):
        with app.app_context():
            db.session.add(Complaint(ticket_number='ALP-1', user_id=world['u']['cit'], authority_id=world['office'],
                                     district_id=world['a'], category='other', description='PRIVATE complaint text'))
            db.session.commit()
        url = f"/profile/{world['u']['cit']}"
        for who in ('other', 'auth'):
            login(client, who)
            body = client.get(url).get_data(as_text=True)
            assert 'PRIVATE complaint text' not in body and 'ALP-1' not in body, who
        for who in ('cit', 'admin'):
            login(client, who)
            assert 'PRIVATE complaint text' in client.get(url).get_data(as_text=True), who


class TestCommunityPosts:
    @pytest.fixture
    def uploads(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'root_path', str(tmp_path))  # posts write to <root>/static/uploads
        from app.routes import posts
        monkeypatch.setattr(posts.ai_service, 'classify_post', lambda content: {'category': 'general'})
        return tmp_path / 'static' / 'uploads'

    def test_post_photo_is_reencoded_without_exif_gps(self, app, client, world, uploads):
        login(client, 'cit')
        response = client.post('/posts/create', data={'content': 'Road blocked', 'district_id': world['a'],
                                                      'photo': (io.BytesIO(jpeg_with_exif()), 'p.jpg', 'image/jpeg')},
                               content_type='multipart/form-data')
        assert response.status_code == 302
        with app.app_context():
            post = Post.query.one()
        stored = uploads / os.path.basename(post.photo_path)
        data = stored.read_bytes()
        assert post.photo_path.endswith('.jpg') and b'SECRET-CAMERA' not in data
        with Image.open(io.BytesIO(data)) as image:
            assert not image.getexif() and image.format == 'JPEG'

    @pytest.mark.parametrize('photo', [(b'<html>not an image</html>', 'x.png', 'image/png'),
                                       (b'GIF89a....', 'x.gif', 'image/gif'),
                                       (b'hello', 'x.txt', 'text/plain')])
    def test_non_images_rejected(self, app, client, world, uploads, photo):
        login(client, 'cit')
        client.post('/posts/create', data={'content': 'x', 'district_id': world['a'],
                                           'photo': (io.BytesIO(photo[0]), photo[1], photo[2])},
                    content_type='multipart/form-data')
        with app.app_context():
            assert Post.query.count() == 0
        assert not uploads.exists() or not any(uploads.iterdir())

    @pytest.mark.parametrize('district', ['abc', '9999', ''])
    def test_invalid_district_rejected(self, app, client, world, uploads, district):
        with app.app_context():
            db.session.get(User, world['u']['cit']).district_id = None  # no fallback district either
            db.session.commit()
        login(client, 'cit')
        client.post('/posts/create', data={'content': 'x', 'district_id': district})
        with app.app_context():
            assert Post.query.count() == 0

    def test_like_and_comment_need_a_real_post(self, app, client, world):
        login(client, 'cit')
        assert client.post('/social/post/999/like').status_code == 404
        assert client.post('/social/post/999/comment', data={'content': 'hi'}).status_code == 404
        with app.app_context():
            assert Like.query.count() == 0 and Comment.query.count() == 0


def test_zero_water_level_is_recorded(app, client, world):
    login(client, 'auth')
    client.post(f"/rivers/{world['river']}/update", data={'water_level': '0', 'description': 'dry'})
    with app.app_context():
        assert RiverUpdate.query.one().water_level == 0.0


@pytest.mark.parametrize('referrer,expected', [('https://evil.example/phish', '/'),
                                               ('http://localhost/districts?x=1', '/districts?x=1')])
def test_language_switch_redirects_only_on_site(client, referrer, expected):
    response = client.get('/language/set/en', headers={'Referer': referrer})
    assert response.status_code == 302 and response.headers['Location'] == expected


class TestLocalisedAlerts:
    def test_headline_in_reader_language(self, app, world):
        with app.app_context():
            incident = create_hazard_event('flood', 'high', 'iot', district_id=world['a'], river_id=world['river'],
                                           title='Rising detected: Kamala River')
            n = Notification.query.filter_by(user_id=world['u']['nepali']).one()
            assert notification_service.localized_title(n, 'en') == n.title == 'Flood detected in Alpha'
            assert notification_service.localized_title(n, 'ne') == 'Alphaमा बाढी पत्ता लाग्यो'
            # the river name is not repeated when the title already contains it
            assert n.message.count('Kamala River') == 1
            assert incident.id

    def test_nepali_reader_sees_nepali_alert_and_push(self, app, client, world, monkeypatch):
        app.config.update(VAPID_PUBLIC_KEY=PUBLIC, VAPID_PRIVATE_KEY=PRIVATE)
        sent = []

        class Resp:
            status_code = 201
        monkeypatch.setattr(web_push.requests, 'post', lambda *a, **k: sent.append(k) or Resp())
        with app.app_context():
            db.session.add(PushSubscription(user_id=world['u']['nepali'], endpoint='https://fcm.googleapis.com/x',
                                            p256dh_key=web_push.b64url_encode(b'\x04' + b'\x01' * 64), auth_key='a'))
            db.session.get(User, world['u']['nepali']).emergency_alert_state = 'granted'
            db.session.commit()
        payloads = []
        from app.services import emergency_dispatcher
        monkeypatch.setattr(emergency_dispatcher, '_send', lambda sub, payload: payloads.append(payload) or True)
        with app.app_context():
            create_hazard_event('landslide', 'critical', 'authority', district_id=world['a'])
        assert payloads[0]['title'] == 'X-MAN आपतकालीन सूचना: Alphaमा पहिरो पत्ता लाग्यो'
        client.post('/auth/login', data={'username': 'nepali', 'password': 'pw'})
        client.get('/language/set/ne')
        [alert] = client.get('/api/emergency/active').get_json()['alerts']
        assert alert['title'] == 'Alphaमा पहिरो पत्ता लाग्यो'
        assert 'Alphaमा पहिरो पत्ता लाग्यो' in client.get('/notifications').get_data(as_text=True)

    def test_overlay_severity_label_is_translated(self, client, world):
        client.post('/auth/login', data={'username': 'nepali', 'password': 'pw'})
        client.get('/language/set/ne')
        body = client.get('/dashboard').get_data(as_text=True)
        assert 'data-high="उच्च"' in body


class TestReportPages:
    def test_hazard_labels_are_human_readable(self, app, client, world):
        login(client, 'cit')
        page = client.get('/report').get_data(as_text=True)
        assert '>Landslide</label>' in page.replace('\n', '') or 'Landslide</label>' in page
        assert 'road_damage</label>' not in page
        # GPS uses the shared widget with honest denied/timeout/unavailable/insecure states
        assert 'data-location-widget' in page and 'Location permission was denied' in page

    def test_unknown_ai_result_explains_the_threshold(self, app, client, world):
        from flask import render_template_string, session
        with app.test_request_context():
            session['language'] = 'en'
            text = render_template_string('{% import "components/ui.html" as ui with context %}'
                                          '{{ ui.ai_result("unknown", 0.0226) }}|{{ ui.ai_result("landslide", 0.9968) }}')
        assert text == 'No hazard recognised · best match 0.02 (needs 0.60)|Landslide · Model confidence 1.00'


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js not installed')
def test_service_worker_only_ever_opens_x_man_pages():
    out = subprocess.run(['node', os.path.join(REPO, 'tests', 'sw_harness.js')], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result['events'] == ['activate', 'install', 'notificationclick', 'push']
    shown = result['shown']
    assert shown[0] == {'title': 'X-MAN EMERGENCY ALERT: Flood', 'url': '/rivers/status?district_id=1',
                        'requireInteraction': True, 'tag': 'xman-hazard-1'}
    assert shown[1]['url'] == '/notifications' and shown[1]['requireInteraction'] is False  # external URL dropped
    assert shown[2]['title'] == 'X-MAN alert'  # malformed payload still shows a safe notification
    assert result['navigated'] == ['/notifications']  # a stored external URL is not followed on click
    assert result['opened'] == ['/hazards/1/response']
