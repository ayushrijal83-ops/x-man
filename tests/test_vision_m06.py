"""M06: vision analysis of citizen photo reports — classification, abstention, failure safety,
report integration, incident/notification safety, path safety, reviewer UI.

Most tests use a stub classifier whose scores come from the decoded pixels (so the stored image
really flows through). One test runs the real SigLIP model and is skipped if it isn't installed.
"""
import io
import os

import pytest
from PIL import Image

from app.extensions import db
from app.models import Authority, CitizenReport, District, Incident, Notification, User
from app.services import citizen_report_service, vision_service
from app.services.vision_service import VisionError, classify

RED, GREEN, BLUE, GRAY, YELLOW = (200, 30, 30), (30, 200, 30), (30, 30, 200), (128, 128, 128), (220, 220, 20)


class PixelStub:
    """Deterministic stand-in for SiglipClassifier: scores depend on the image's mean colour."""

    def __init__(self, fail=False):
        self.fail = fail
        self.seen = []

    def scores(self, image):
        if self.fail:
            raise RuntimeError('boom')
        self.seen.append(image.copy())
        r, g, b = [sum(c) / len(c) for c in zip(*image.getdata())]
        if r > 150 and g > 150:
            return {'road_damage': 0.99, 'landslide': 0.005, 'other': 0.005}
        if r > 150:
            return {'road_damage': 0.91, 'landslide': 0.04, 'other': 0.05}
        if g > 150:
            return {'road_damage': 0.06, 'landslide': 0.84, 'other': 0.10}
        if b > 150:
            return {'road_damage': 0.02, 'landslide': 0.03, 'other': 0.95}
        return {'road_damage': 0.32, 'landslide': 0.28, 'other': 0.40}


@pytest.fixture
def stub(app, monkeypatch):
    s = PixelStub()
    monkeypatch.setattr(vision_service, '_classifier', s)
    app.config['VISION_ENABLED'] = True
    return s


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


def _jpeg(color, size=(64, 48)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='JPEG')
    return buf.getvalue()


def _submit(client, world, color=RED, hazard_type='road_damage', **extra):
    _login(client, 'citizen_a')
    data = {'hazard_type': hazard_type, 'district_id': str(world['a']),
            'latitude': '27.2', 'longitude': '85.9',
            'image': (io.BytesIO(_jpeg(color)), 'photo.jpg', 'image/jpeg'), **extra}
    response = client.post('/api/reports', data=data, content_type='multipart/form-data')
    assert response.status_code == 201, response.get_json()
    return response


def _report(app, report_id=None):
    with app.app_context():
        report = db.session.get(CitizenReport, report_id) if report_id else CitizenReport.query.one()
        db.session.expunge(report)
        return report


class TestClassify:
    @pytest.mark.parametrize('color, label, confidence', [
        (RED, 'road_damage', 0.91),
        (GREEN, 'landslide', 0.84),
        (BLUE, 'unknown', 0.03),  # "other" wins: abstain, never forced into a hazard class
        (GRAY, 'unknown', 0.32),  # best hazard class below threshold
    ])
    def test_labels_and_abstention(self, app, stub, color, label, confidence):
        result = classify(_jpeg(color))
        assert (result.label, result.confidence) == (label, confidence)
        assert result.model == 'google/siglip-base-patch16-224'
        assert result.model_version == app.config['VISION_MODEL_REVISION'][:12]

    def test_threshold_is_configurable(self, app, stub):
        app.config['VISION_CONFIDENCE_THRESHOLD'] = 0.95
        assert classify(_jpeg(RED)).label == 'unknown'
        app.config['VISION_CONFIDENCE_THRESHOLD'] = 0.9
        assert classify(_jpeg(RED)).label == 'road_damage'

    @pytest.mark.parametrize('data', [b'', b'not an image', b'%PDF-1.4', _jpeg(RED)[:40]])
    def test_invalid_image_rejected(self, app, stub, data):
        with pytest.raises(VisionError, match='could not be decoded'):
            classify(data)
        assert stub.seen == []

    def test_only_accepts_bytes_never_a_path(self, app, stub, tmp_path):
        secret = tmp_path / 'secret.txt'
        secret.write_text('top secret')
        for value in ('../../secret.txt', str(secret).encode()):
            with pytest.raises(VisionError):
                classify(value if isinstance(value, bytes) else value.encode())
        assert stub.seen == []

    def test_missing_model_fails_safely(self, app, monkeypatch, tmp_path):
        monkeypatch.setattr(vision_service, '_classifier', None)
        app.config['VISION_MODEL_PATH'] = str(tmp_path / 'no-model')
        with pytest.raises(VisionError) as info:
            classify(_jpeg(RED))
        assert 'not installed' in str(info.value) and str(tmp_path) not in str(info.value)

    def test_unloadable_model_or_missing_dependency(self, app, monkeypatch, tmp_path):
        (tmp_path / 'model.safetensors').write_bytes(b'corrupt')
        monkeypatch.setattr(vision_service, '_classifier', None)
        app.config['VISION_MODEL_PATH'] = str(tmp_path)

        def broken(path):
            raise ImportError('No module named torch')
        monkeypatch.setattr(vision_service, 'SiglipClassifier', broken)
        with pytest.raises(VisionError, match=r'could not be loaded \(ImportError\)'):
            classify(_jpeg(RED))
        assert vision_service._classifier is None  # retried next time, not cached as broken

    def test_inference_exception(self, app, monkeypatch):
        monkeypatch.setattr(vision_service, '_classifier', PixelStub(fail=True))
        with pytest.raises(VisionError, match=r'inference failed \(RuntimeError\)'):
            classify(_jpeg(RED))

    def test_vision_service_has_no_incident_or_notification_access(self):
        names = set(vars(vision_service))
        assert not names & {'db', 'Incident', 'notification_service', 'hazard_event_service', 'CitizenReport'}


class TestReportIntegration:
    def test_submission_stores_ai_evidence(self, app, client, world, stub):
        response = _submit(client, world, RED)
        assert 'ai_analysis' not in response.get_json()['report']  # citizens don't see model output
        report = _report(app)
        assert (report.ai_status, report.ai_label, report.ai_confidence) == ('completed', 'road_damage', 0.91)
        assert report.ai_model == 'google/siglip-base-patch16-224' and report.ai_analyzed_at is not None

    def test_analyzes_the_stored_reencoded_image(self, app, client, world, stub, upload_dir):
        _submit(client, world, RED)
        stored = Image.open(upload_dir / _report(app).image_filename)
        assert len(stub.seen) == 1
        assert stub.seen[0].size == stored.size and list(stub.seen[0].getdata()) == list(stored.convert('RGB').getdata())

    @pytest.mark.parametrize('citizen, color, ai', [('road_damage', GREEN, 'landslide'),
                                                    ('landslide', RED, 'road_damage')])
    def test_disagreement_keeps_citizen_type(self, app, client, world, stub, citizen, color, ai):
        _submit(client, world, color, hazard_type=citizen)
        report = _report(app)
        assert (report.hazard_type, report.ai_label) == (citizen, ai)
        with app.app_context():
            assert Incident.query.one().event_type == citizen

    def test_unknown_keeps_report_valid(self, app, client, world, stub):
        _submit(client, world, GRAY)
        report = _report(app)
        assert (report.status, report.ai_label, report.ai_confidence) == ('submitted', 'unknown', 0.32)

    @pytest.mark.parametrize('color', [YELLOW, GRAY])  # 0.99 and below-threshold
    def test_ai_never_accepts_confirms_or_escalates(self, app, client, world, stub, color):
        _submit(client, world, color)
        _submit(client, world, color)  # second report merges into the same incident
        with app.app_context():
            assert {r.status for r in CitizenReport.query} == {'submitted'}
            if color == YELLOW:
                assert {r.ai_confidence for r in CitizenReport.query} == {0.99}
            incident = Incident.query.one()
            assert (incident.status, incident.severity) == ('detected', 'medium')
            assert incident.affected_district_ids == [world['a']]
            for kind in ('hazard_escalated', 'hazard_confirmed', 'hazard_resolved'):
                assert Notification.query.filter_by(type=kind).count() == 0

    def test_inference_failure_keeps_report(self, app, client, world, monkeypatch):
        app.config['VISION_ENABLED'] = True
        monkeypatch.setattr(vision_service, '_classifier', PixelStub(fail=True))
        report_id = _submit(client, world, RED).get_json()['report']['id']
        report = _report(app)
        assert (report.status, report.ai_status, report.ai_label, report.ai_confidence) == \
            ('submitted', 'failed', None, None)
        assert report.incident_id is not None
        _login(client, 'auth_a')
        image = client.get(f'/api/reports/{report_id}/image')
        assert image.status_code == 200
        image.close()

    def test_missing_model_on_submit_keeps_report(self, app, client, world, monkeypatch, tmp_path):
        app.config.update(VISION_ENABLED=True, VISION_MODEL_PATH=str(tmp_path / 'none'))
        monkeypatch.setattr(vision_service, '_classifier', None)
        _submit(client, world, RED)
        assert _report(app).ai_status == 'failed'

    def test_disabled_leaves_not_analyzed(self, app, client, world):
        _submit(client, world, RED)
        assert _report(app).ai_status == 'not_analyzed'

    def test_tampered_filename_is_not_read(self, app, client, world, stub, tmp_path):
        _submit(client, world, RED)
        with app.app_context():
            report = CitizenReport.query.one()
            report.image_filename = '../../secret.txt'
            db.session.commit()
            stub.seen.clear()
            citizen_report_service.analyze_report(report)
            assert report.ai_status == 'failed' and stub.seen == []

    def test_deleted_image_fails_without_leaking_path(self, app, client, world, stub, upload_dir):
        _submit(client, world, RED)
        os.remove(upload_dir / _report(app).image_filename)
        _login(client, 'auth_a')
        response = client.post(f"/api/reports/{_report(app).id}/analyze")
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert response.get_json()['report']['ai_analysis']['status'] == 'failed'
        assert str(upload_dir) not in body and 'image_filename' not in body


class TestApi:
    def test_reviewer_sees_ai_analysis(self, app, client, world, stub):
        report_id = _submit(client, world, GREEN).get_json()['report']['id']
        _login(client, 'auth_a')
        ai = client.get(f'/api/reports/{report_id}').get_json()['report']['ai_analysis']
        assert ai['status'] == 'completed' and ai['label'] == 'landslide' and ai['confidence'] == 0.84
        assert set(ai) == {'status', 'label', 'confidence', 'model', 'model_version', 'analyzed_at'}

    def test_reporter_does_not_see_ai_analysis(self, app, client, world, stub):
        report_id = _submit(client, world, GREEN).get_json()['report']['id']
        assert 'ai_analysis' not in client.get(f'/api/reports/{report_id}').get_json()['report']
        assert 'ai_analysis' not in client.get('/api/reports').get_json()['reports'][0]

    def test_analyze_rerun_after_failure(self, app, client, world, monkeypatch):
        app.config['VISION_ENABLED'] = True
        monkeypatch.setattr(vision_service, '_classifier', PixelStub(fail=True))
        report_id = _submit(client, world, RED).get_json()['report']['id']
        monkeypatch.setattr(vision_service, '_classifier', PixelStub())
        _login(client, 'auth_a')
        response = client.post(f'/api/reports/{report_id}/analyze', json={'path': '../../secret.txt'})
        assert response.status_code == 200
        assert response.get_json()['report']['ai_analysis']['label'] == 'road_damage'
        assert response.get_json()['report']['status'] == 'submitted'

    def test_analyze_authorization(self, app, client, world, stub):
        report_id = _submit(client, world, RED).get_json()['report']['id']
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 403  # reporter (citizen)
        _login(client, 'citizen_a2')
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 403
        _login(client, 'auth_b')
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 404  # other district
        _login(client, 'admin')
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 200
        assert client.post('/api/reports/99999/analyze').status_code == 404
        client.get('/auth/logout')
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 401

    def test_analyze_disabled_is_503(self, app, client, world):
        report_id = _submit(client, world, RED).get_json()['report']['id']
        _login(client, 'auth_a')
        assert client.post(f'/api/reports/{report_id}/analyze').status_code == 503

    def test_review_still_independent_of_incident(self, app, client, world, stub):
        report_id = _submit(client, world, YELLOW).get_json()['report']['id']
        _login(client, 'auth_a')
        assert client.post(f'/api/reports/{report_id}/review', json={'status': 'accepted'}).status_code == 200
        with app.app_context():
            assert Incident.query.one().status == 'detected'


class TestReviewPage:
    def test_reviewer_page_separates_citizen_ai_and_incident(self, app, client, world, stub):
        _submit(client, world, GREEN, hazard_type='road_damage', description='Crack near school')
        _login(client, 'auth_a')
        client.get('/language/set/en')
        body = client.get('/reports/review').get_data(as_text=True)
        # labels are human-readable since the final QA pass ('Landslide · Model confidence 0.84', was raw keys)
        for text in ('Citizen report', 'AI analysis', 'Hazard event', 'Crack near school', 'Landslide',
                     'differs from citizen', 'Model confidence 0.84', 'google/siglip-base-patch16-224',
                     'data-status="accepted"', '/api/reports/'):
            assert text in body
        client.get('/language/set/ne')
        assert 'एआई विश्लेषण' in client.get('/reports/review').get_data(as_text=True)

    def test_other_district_and_citizens_cannot_see(self, app, client, world, stub):
        _submit(client, world, RED, description='Only for A')
        assert client.get('/reports/review').status_code == 403
        _login(client, 'auth_b')
        assert 'Only for A' not in client.get('/reports/review').get_data(as_text=True)

    def test_my_reports_shows_no_model_output(self, app, client, world, stub):
        _submit(client, world, GREEN)
        body = client.get('/reports/mine').get_data(as_text=True)
        assert 'siglip' not in body and 'Model confidence' not in body


MODEL_DIR = os.environ.get('VISION_MODEL_PATH') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'models', 'siglip-base-patch16-224')


@pytest.mark.skipif(not os.path.isfile(os.path.join(MODEL_DIR, 'model.safetensors')),
                    reason='vision model not installed (scripts/download_vision_model.py)')
def test_real_model_abstains_on_a_blank_image(app, monkeypatch):
    pytest.importorskip('torch')
    pytest.importorskip('transformers')
    monkeypatch.setattr(vision_service, '_classifier', None)
    app.config['VISION_MODEL_PATH'] = MODEL_DIR
    result = classify(_jpeg(GRAY, size=(320, 240)))
    assert result.label == 'unknown'
    assert 0.0 <= result.confidence < app.config['VISION_CONFIDENCE_THRESHOLD']
