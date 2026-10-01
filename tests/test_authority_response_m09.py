"""M09: Authority Response System — lifecycle, audit trail, investigation notes, response actions,
authorization matrix, privacy, notifications, integrity/concurrency, XSS, response page."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (Authority, District, Incident, IncidentInvestigation, IncidentResponseAction,
                        IncidentStatusHistory, Notification, User)
from app.services import hazard_event_service
from app.services.hazard_event_service import TransitionConflict, add_affected_district, create_hazard_event

FULL_PATH = ['investigating', 'confirmed', 'response', 'resolved']


@pytest.fixture
def world(app):
    with app.app_context():
        a, b, c = (District(name=f'District {x}', province='P') for x in 'ABC')
        db.session.add_all([a, b, c])
        db.session.commit()
        auth_a = Authority(name='Auth A', category='water', district_id=a.id)
        auth_b = Authority(name='Auth B', category='water', district_id=b.id)
        db.session.add_all([auth_a, auth_b])
        db.session.commit()
        users = {}
        for name, role, district_id, authority_id in [
            ('citizen_a', 'citizen', a.id, None), ('citizen_c', 'citizen', c.id, None),
            ('auth_a', 'authority', a.id, auth_a.id), ('auth_b', 'authority', b.id, auth_b.id),
            ('auth_unlinked', 'authority', a.id, None), ('admin', 'admin', None, None),
        ]:
            user = User(username=name, email=f'{name}@t.np', role=role, district_id=district_id,
                        authority_id=authority_id)
            user.set_password('pw')
            db.session.add(user)
            users[name] = user
        db.session.commit()
        flood = create_hazard_event('flood', 'high', 'iot', district_id=a.id, title='River A rising',
                                    source_reference='device_7')
        other = create_hazard_event('landslide', 'medium', 'authority', district_id=b.id)
        return {'a': a.id, 'b': b.id, 'c': c.id, 'u': {k: v.id for k, v in users.items()},
                'flood': flood.id, 'other': other.id}


def _login(client, username):
    client.get('/auth/logout')
    path = '/auth/login' if username.startswith('citizen') else '/auth/authority/login'
    client.post(path, data={'username': username, 'password': 'pw'})


def _status(client, event_id, status, note=None, **extra):
    body = {'status': status, **extra}
    if note is not None:
        body['note'] = note
    return client.post(f'/api/hazards/{event_id}/status', json=body)


def _walk(client, event_id, statuses):
    for status in statuses:
        note = f'note for {status}' if status in ('resolved', 'rejected') else None
        response = _status(client, event_id, status, note)
        assert response.status_code == 200, response.get_json()


def _row(app, event_id):
    with app.app_context():
        incident = db.session.get(Incident, event_id)
        return incident.status, IncidentStatusHistory.query.filter_by(incident_id=event_id).count()


def _history(app, event_id):
    with app.app_context():
        return [(h.previous_status, h.new_status, h.changed_by.username if h.changed_by else None, h.note)
                for h in IncidentStatusHistory.query.filter_by(incident_id=event_id).order_by(IncidentStatusHistory.id)]


# ----------------------------------------------------------------- lifecycle

class TestLifecycle:
    def test_full_path_with_audit_trail(self, app, client, world):
        _login(client, 'auth_a')
        for status in FULL_PATH:
            note = 'Water below danger mark; inspection found no impact.' if status == 'resolved' else None
            response = _status(client, world['flood'], status, note)
            assert response.status_code == 200, response.get_json()
            assert response.get_json()['new_status'] == status
        assert _history(app, world['flood']) == [
            ('detected', 'investigating', 'auth_a', None),
            ('investigating', 'confirmed', 'auth_a', None),
            ('confirmed', 'response', 'auth_a', None),
            ('response', 'resolved', 'auth_a', 'Water below danger mark; inspection found no impact.'),
        ]
        with app.app_context():
            incident = db.session.get(Incident, world['flood'])
            assert incident.resolved_at is not None and incident.description is None

    @pytest.mark.parametrize('path', [['rejected'], ['investigating', 'rejected']])
    def test_rejected_paths(self, app, client, world, path):
        _login(client, 'auth_a')
        _walk(client, world['flood'], path)
        assert _row(app, world['flood']) == ('rejected', len(path))

    def test_confirmed_to_resolved_still_valid(self, app, client, world):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['investigating', 'confirmed', 'resolved'])
        assert _row(app, world['flood'])[0] == 'resolved'

    @pytest.mark.parametrize('path, attempt', [
        (FULL_PATH, 'investigating'), (FULL_PATH, 'confirmed'), (FULL_PATH, 'response'),
        (['rejected'], 'confirmed'), (['rejected'], 'response'), (['rejected'], 'investigating'),
        ([], 'confirmed'), ([], 'response'), ([], 'resolved'), (['investigating'], 'response'),
        ([], 'bogus'), ([], ''),
    ])
    def test_invalid_transitions_rejected_without_history(self, app, client, world, path, attempt):
        _login(client, 'auth_a')
        _walk(client, world['flood'], path)
        before = _row(app, world['flood'])
        response = _status(client, world['flood'], attempt, 'some reason')
        assert response.status_code == 400
        assert _row(app, world['flood']) == before

    @pytest.mark.parametrize('note', [None, '', '   ', ['x'], {'x': 1}, 5, 'x' * 2001])
    def test_resolution_note_required_and_validated(self, app, client, world, note):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['investigating', 'confirmed', 'response'])
        body = {'status': 'resolved'} if note is None else {'status': 'resolved', 'note': note}
        assert client.post(f"/api/hazards/{world['flood']}/status", json=body).status_code == 400
        assert _row(app, world['flood']) == ('response', 3)

    def test_legacy_resolve_and_reject_endpoints_require_notes(self, app, client, world):
        _login(client, 'auth_a')
        assert client.post(f"/api/hazards/{world['flood']}/reject", json={}).status_code == 400
        assert client.post(f"/api/hazards/{world['flood']}/reject", json={'reason': 'gauge fault'}).status_code == 200
        assert _history(app, world['flood']) == [('detected', 'rejected', 'auth_a', 'gauge fault')]

    def test_patch_status_follows_same_rules(self, app, client, world):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['investigating', 'confirmed'])
        url = f"/api/hazards/{world['flood']}"
        assert client.patch(url, json={'status': 'resolved'}).status_code == 400
        assert _row(app, world['flood']) == ('confirmed', 2)
        assert client.patch(url, json={'status': 'resolved', 'note': 'done'}).status_code == 200
        assert _history(app, world['flood'])[-1] == ('confirmed', 'resolved', 'auth_a', 'done')

    def test_duplicate_request_creates_one_history_row(self, app, client, world):
        _login(client, 'auth_a')
        assert _status(client, world['flood'], 'investigating').status_code == 200
        assert _status(client, world['flood'], 'investigating').status_code == 400
        assert _row(app, world['flood']) == ('investigating', 1)


# ----------------------------------------------------------------- integrity / concurrency

class TestIntegrity:
    def test_stale_object_cannot_double_transition(self, app, world):
        with app.app_context():
            stale = db.session.get(Incident, world['flood'])
            assert stale.status == 'detected'
            # another request moves the row first (stale object still says 'detected')
            Incident.query.filter_by(id=stale.id).update({'status': 'investigating'}, synchronize_session=False)
            IncidentStatusHistory.query.delete()
            with pytest.raises(TransitionConflict):
                hazard_event_service.transition_event_status(stale, 'investigating', actor_id=None)
        assert _row(app, world['flood']) == ('detected', 0)  # rolled back as a whole

    def test_history_failure_rolls_back_status(self, app, world, monkeypatch):
        real = hazard_event_service.IncidentStatusHistory
        monkeypatch.setattr(hazard_event_service, 'IncidentStatusHistory',
                            lambda **kw: real(**{**kw, 'new_status': None}))  # violates NOT NULL
        with app.app_context():
            incident = db.session.get(Incident, world['flood'])
            with pytest.raises(IntegrityError):
                hazard_event_service.transition_event_status(incident, 'investigating')
        assert _row(app, world['flood']) == ('detected', 0)

    def test_conflict_maps_to_409(self, app, client, world, monkeypatch):
        _login(client, 'auth_a')

        def conflict(*args, **kwargs):
            raise TransitionConflict('Hazard status was changed by someone else; reload and try again')
        monkeypatch.setattr(hazard_event_service, 'transition_event_status', conflict)
        assert _status(client, world['flood'], 'investigating').status_code == 409


# ----------------------------------------------------------------- authorization matrix

ENDPOINTS = [
    ('get', '/api/hazards/{id}/status-history', None),
    ('get', '/api/hazards/{id}/investigations', None),
    ('get', '/api/hazards/{id}/response-actions', None),
    ('post', '/api/hazards/{id}/status', {'status': 'investigating'}),
    ('post', '/api/hazards/{id}/resolve', {'resolution_notes': 'x'}),
    ('post', '/api/hazards/{id}/reject', {'reason': 'x'}),
    ('post', '/api/hazards/{id}/investigations', {'note': 'x'}),
    ('post', '/api/hazards/{id}/response-actions', {'action_type': 'monitor_area', 'description': 'x'}),
    ('patch', '/api/hazards/{id}/response-actions/{action}', {'status': 'in_progress'}),
]


class TestAuthorization:
    @pytest.fixture
    def action_id(self, app, world):
        with app.app_context():
            action = IncidentResponseAction(incident_id=world['flood'], author_id=world['u']['auth_a'],
                                            action_type='monitor_area', description='watch gauge')
            db.session.add(action)
            db.session.commit()
            return action.id

    @pytest.mark.parametrize('method, url, body', ENDPOINTS)
    @pytest.mark.parametrize('who, expected', [(None, 401), ('citizen_a', 403), ('auth_b', 403),
                                               ('auth_unlinked', 403)])
    def test_denied(self, app, client, world, action_id, method, url, body, who, expected):
        if who:
            _login(client, who)
        response = getattr(client, method)(url.format(id=world['flood'], action=action_id), json=body)
        assert response.status_code == expected
        assert _row(app, world['flood']) == ('detected', 0)
        with app.app_context():
            assert IncidentInvestigation.query.count() == 0 and IncidentResponseAction.query.count() == 1

    @pytest.mark.parametrize('method, url, body', ENDPOINTS[:3] + ENDPOINTS[6:])
    @pytest.mark.parametrize('who', ['auth_a', 'admin'])
    def test_allowed(self, client, world, action_id, method, url, body, who):
        _login(client, who)
        response = getattr(client, method)(url.format(id=world['flood'], action=action_id), json=body)
        assert response.status_code in (200, 201), response.get_json()

    def test_admin_operates_system_wide(self, app, client, world):
        _login(client, 'admin')
        _walk(client, world['other'], FULL_PATH)
        assert _history(app, world['other'])[0][2] == 'admin'

    def test_history_is_read_only(self, client, world):
        _login(client, 'admin')
        for method in ('post', 'patch', 'delete'):
            assert getattr(client, method)(f"/api/hazards/{world['flood']}/status-history", json={}).status_code == 405

    def test_response_page_access(self, client, world):
        url = f"/hazards/{world['flood']}/response"
        assert client.get(url).status_code == 302
        for who, code in [('citizen_a', 403), ('auth_b', 403), ('auth_unlinked', 403), ('auth_a', 200), ('admin', 200)]:
            _login(client, who)
            assert client.get(url).status_code == code
        assert client.get('/hazards/99999/response').status_code == 404


# ----------------------------------------------------------------- input manipulation

class TestInputManipulation:
    @pytest.mark.parametrize('field, value', [('severity', 'critical'), ('source', 'authority'), ('risk_level', 3),
                                              ('confidence', 0.99), ('reporter_id', 1), ('device_id', 1),
                                              ('authority_id', 1), ('ai_label', 'landslide')])
    def test_operational_fields_rejected(self, app, client, world, field, value):
        _login(client, 'auth_a')
        assert _status(client, world['flood'], 'investigating', **{field: value}).status_code == 400
        assert client.post(f"/api/hazards/{world['flood']}/investigations",
                           json={'note': 'x', field: value}).status_code == 400
        assert client.post(f"/api/hazards/{world['flood']}/response-actions",
                           json={'action_type': 'other', 'description': 'x', field: value}).status_code == 400
        with app.app_context():
            incident = db.session.get(Incident, world['flood'])
            assert (incident.status, incident.severity, incident.source) == ('detected', 'high', 'iot')
            assert IncidentInvestigation.query.count() == 0 and IncidentResponseAction.query.count() == 0


# ----------------------------------------------------------------- investigation notes

class TestInvestigations:
    def test_add_and_list(self, app, client, world):
        _login(client, 'auth_a')
        text = 'Field team reached the downstream bridge.\nWater above the marker.'
        response = client.post(f"/api/hazards/{world['flood']}/investigations", json={'note': f'  {text}  '})
        assert response.status_code == 201
        note = response.get_json()['investigation']
        assert note['note'] == text and note['author'] == 'auth_a' and note['created_at']
        listed = client.get(f"/api/hazards/{world['flood']}/investigations").get_json()['investigations']
        assert [n['note'] for n in listed] == [text]
        assert set(listed[0]) == {'id', 'note', 'author', 'created_at'}  # no user ids or emails

    @pytest.mark.parametrize('note', [None, '', '   ', ['a'], {'a': 1}, 3, 'x' * 2001])
    def test_invalid_notes(self, app, client, world, note):
        _login(client, 'auth_a')
        body = {} if note is None else {'note': note}
        assert client.post(f"/api/hazards/{world['flood']}/investigations", json=body).status_code == 400
        with app.app_context():
            assert IncidentInvestigation.query.count() == 0

    def test_closed_incident_takes_no_new_entries(self, app, client, world):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['rejected'])
        assert client.post(f"/api/hazards/{world['flood']}/investigations", json={'note': 'late'}).status_code == 409
        assert client.post(f"/api/hazards/{world['flood']}/response-actions",
                           json={'action_type': 'other', 'description': 'late'}).status_code == 409


# ----------------------------------------------------------------- response actions

class TestResponseActions:
    def _create(self, client, world, **body):
        payload = {'action_type': 'close_road', 'description': 'Close the river road', **body}
        return client.post(f"/api/hazards/{world['flood']}/response-actions", json=payload)

    def test_create_update_complete(self, app, client, world):
        _login(client, 'auth_a')
        response = self._create(client, world)
        assert response.status_code == 201
        action = response.get_json()['response_action']
        assert (action['status'], action['completed_at'], action['author']) == ('planned', None, 'auth_a')
        url = f"/api/hazards/{world['flood']}/response-actions/{action['id']}"
        assert client.patch(url, json={'status': 'in_progress', 'description': 'Road closed at km 4'}).status_code == 200
        done = client.patch(url, json={'status': 'completed'}).get_json()['response_action']
        assert done['status'] == 'completed' and done['completed_at'] and done['description'] == 'Road closed at km 4'
        assert client.patch(url, json={'status': 'cancelled'}).status_code == 409  # final
        listed = client.get(f"/api/hazards/{world['flood']}/response-actions").get_json()['response_actions']
        assert [a['status'] for a in listed] == ['completed']

    def test_create_completed_sets_server_time_and_cancel(self, client, world):
        _login(client, 'admin')
        done = self._create(client, world, status='completed').get_json()['response_action']
        assert done['completed_at'] is not None
        planned = self._create(client, world, action_type='deploy_team').get_json()['response_action']
        url = f"/api/hazards/{world['flood']}/response-actions/{planned['id']}"
        cancelled = client.patch(url, json={'status': 'cancelled'}).get_json()['response_action']
        assert cancelled['status'] == 'cancelled' and cancelled['completed_at'] is None

    @pytest.mark.parametrize('body', [
        {'action_type': 'launch_rocket'}, {'action_type': None}, {'status': 'done'}, {'description': ''},
        {'description': '   '}, {'description': ['x']}, {'description': 'x' * 1001},
        {'completed_at': '2020-01-01T00:00:00'}, {'author_id': 1}, {'incident_id': 2},
    ])
    def test_invalid_create(self, app, client, world, body):
        _login(client, 'auth_a')
        assert self._create(client, world, **body).status_code == 400
        with app.app_context():
            assert IncidentResponseAction.query.count() == 0

    @pytest.mark.parametrize('body, code', [({'status': 'planned_x'}, 400), ({'status': 'planned'}, 200),
                                            ({'action_type': 'other'}, 400), ({'completed_at': 'x'}, 400),
                                            ({}, 400), ({'description': ''}, 400)])
    def test_invalid_update(self, client, world, body, code):
        _login(client, 'auth_a')
        action = self._create(client, world).get_json()['response_action']
        url = f"/api/hazards/{world['flood']}/response-actions/{action['id']}"
        assert client.patch(url, json=body).status_code == code

    def test_in_progress_cannot_go_back_to_planned(self, client, world):
        _login(client, 'auth_a')
        action = self._create(client, world, status='in_progress').get_json()['response_action']
        url = f"/api/hazards/{world['flood']}/response-actions/{action['id']}"
        assert client.patch(url, json={'status': 'planned'}).status_code == 400

    def test_action_must_belong_to_incident(self, client, world):
        _login(client, 'admin')
        action = self._create(client, world).get_json()['response_action']
        assert client.patch(f"/api/hazards/{world['other']}/response-actions/{action['id']}",
                            json={'status': 'completed'}).status_code == 404
        assert client.patch(f"/api/hazards/{world['flood']}/response-actions/99999",
                            json={'status': 'completed'}).status_code == 404


# ----------------------------------------------------------------- privacy

class TestPrivacy:
    def _populate(self, client, world):
        _login(client, 'auth_a')
        client.post(f"/api/hazards/{world['flood']}/investigations", json={'note': 'SECRET-NOTE officer saw'})
        client.post(f"/api/hazards/{world['flood']}/response-actions",
                    json={'action_type': 'evacuate_area', 'description': 'SECRET-ACTION evacuate ward 3'})
        _walk(client, world['flood'], ['investigating', 'confirmed', 'response'])

    def test_citizen_sees_public_status_only(self, app, client, world):
        self._populate(client, world)
        _login(client, 'citizen_a')
        api = [client.get(url).get_data(as_text=True) for url in (
            f"/api/hazards/{world['flood']}", '/api/hazards', '/api/dashboard', '/api/notifications')]
        pages = [client.get(url).get_data(as_text=True) for url in ('/monitoring', '/notifications')]
        for body in api + pages:
            for secret in ('SECRET-NOTE', 'SECRET-ACTION', 'auth_a', 'source_reference', 'device_7'):
                assert secret not in body
        for body in api:  # manager-only keys (the page's JS source naturally names them)
            for key in ('response_url', 'status_history', '"notes"', '"open_actions"'):
                assert key not in body
        event = client.get(f"/api/hazards/{world['flood']}").get_json()
        assert event['status'] == 'response'
        assert [d['name'] for d in event['affected_districts']] == ['District A']

    def test_resolution_note_never_public(self, app, client, world):
        self._populate(client, world)
        _status(client, world['flood'], 'resolved', 'SECRET-RESOLUTION water receded')
        _login(client, 'citizen_a')
        for url in (f"/api/hazards/{world['flood']}", '/api/hazards?status=resolved', '/api/notifications'):
            assert 'SECRET-RESOLUTION' not in client.get(url).get_data(as_text=True)

    def test_manager_dashboard_shows_response_state(self, client, world):
        self._populate(client, world)
        _login(client, 'auth_a')
        hazard = next(h for h in client.get('/api/dashboard').get_json()['hazards'] if h['id'] == world['flood'])
        assert hazard['status'] == 'response'
        assert hazard['response'] == {'notes': 1, 'open_actions': 1, 'actions': 1}
        assert hazard['response_url'] == f"/hazards/{world['flood']}/response"
        assert 'SECRET' not in str(hazard)


# ----------------------------------------------------------------- notifications (M03/M04 unchanged)

class TestNotifications:
    def _counts(self, app):
        with app.app_context():
            return dict(db.session.query(Notification.type, db.func.count()).group_by(Notification.type).all())

    def test_lifecycle_does_not_duplicate_alerts(self, app, client, world):
        start = self._counts(app)
        _login(client, 'auth_a')
        _status(client, world['flood'], 'investigating')
        client.post(f"/api/hazards/{world['flood']}/investigations", json={'note': 'n'})
        client.post(f"/api/hazards/{world['flood']}/response-actions", json={'action_type': 'other', 'description': 'd'})
        assert self._counts(app) == start  # no alert for investigation, notes or actions
        _status(client, world['flood'], 'confirmed')
        confirmed = self._counts(app)
        assert confirmed['hazard_detected'] == start['hazard_detected']
        assert confirmed['hazard_confirmed'] > 0  # existing M03 rule
        _status(client, world['flood'], 'response')
        assert self._counts(app) == confirmed  # response itself sends nothing
        _status(client, world['flood'], 'resolved', 'done')
        resolved = self._counts(app)
        assert resolved['hazard_resolved'] == confirmed['hazard_confirmed']  # same recipients, once each
        assert resolved['hazard_detected'] == start['hazard_detected']
        assert resolved.get('hazard_escalated', 0) == start.get('hazard_escalated', 0)

    def test_area_expansion_during_response_brings_new_users_up_to_date(self, app, client, world):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['investigating', 'confirmed', 'response'])
        with app.app_context():
            add_affected_district(db.session.get(Incident, world['flood']), world['c'])
            types = sorted(n.type for n in Notification.query.filter_by(user_id=world['u']['citizen_c']))
        assert types == ['hazard_confirmed', 'hazard_detected']

    def test_response_status_is_active_everywhere(self, client, world):
        _login(client, 'auth_a')
        _walk(client, world['flood'], ['investigating', 'confirmed', 'response'])
        _login(client, 'citizen_a')
        assert world['flood'] in [e['id'] for e in client.get('/api/hazards').get_json()['events']]
        assert client.get('/api/dashboard').get_json()['summary']['by_type']['flood'] == 1


# ----------------------------------------------------------------- page / XSS

class TestResponsePage:
    def test_only_valid_controls_shown(self, client, world):
        _login(client, 'auth_a')
        client.get('/language/set/en')
        url = f"/hazards/{world['flood']}/response"
        body = client.get(url).get_data(as_text=True)
        assert 'data-transition="investigating"' in body and 'data-transition="rejected"' in body
        assert 'data-transition="confirmed"' not in body and 'data-transition="resolved"' not in body
        _walk(client, world['flood'], ['investigating', 'confirmed'])
        body = client.get(url).get_data(as_text=True)
        assert 'data-transition="response"' in body and 'data-transition="resolved"' in body
        assert 'Risk assessment' in body and 'Timeline' in body
        _walk(client, world['flood'], ['response', 'resolved'])
        body = client.get(url).get_data(as_text=True)
        assert 'data-transition=' not in body and 'id="note-form"' not in body and 'cannot be reopened' in body
        assert body.count('class="k-status"') == 4 and 'Response in progress' in body

    @pytest.mark.parametrize('payload', ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>'])
    def test_user_content_escaped(self, client, world, payload):
        _login(client, 'auth_a')
        client.post(f"/api/hazards/{world['flood']}/investigations", json={'note': payload})
        client.post(f"/api/hazards/{world['flood']}/response-actions",
                    json={'action_type': 'other', 'description': payload})
        body = client.get(f"/hazards/{world['flood']}/response").get_data(as_text=True)
        assert payload not in body
        assert payload.replace('<', '&lt;').replace('>', '&gt;') in body
        assert 'innerHTML' not in body

    def test_nepali(self, client, world):
        _login(client, 'auth_a')
        client.get('/language/set/ne')
        assert 'अनुसन्धान सुरु गर्नुहोस्' in client.get(f"/hazards/{world['flood']}/response").get_data(as_text=True)
