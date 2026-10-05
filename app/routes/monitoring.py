"""Disaster Monitoring Dashboard (M07).

Page: GET /monitoring            (any logged-in user; content depends on role)
API:  GET /api/dashboard[?district_id=<id>]   (district_id: admins only)

Read-only. The page polls the API; all scoping happens in dashboard_service.
"""
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models import District, Incident
from app.models.incident import ACTIVE_STATUSES
from app.models.incident_response import ACTION_STATUSES, ACTION_TRANSITIONS, ACTION_TYPES
from app.routes.hazard_events import api_login_required
from app.services import authority_response_service as response_service, dashboard_service, risk_service

monitoring_bp = Blueprint('monitoring', __name__)

POLL_SECONDS = 10  # H03.10: live telemetry/device status (was 30)


@monitoring_bp.route('/monitoring')
@login_required
def monitoring_page():
    districts = District.query.order_by(District.name).all() if current_user.role == 'admin' else []
    return render_template('pages/monitoring.html', poll_seconds=POLL_SECONDS, districts=districts,
                           is_manager=dashboard_service.is_manager(current_user))


@monitoring_bp.route('/hazards/<int:event_id>/response')
@login_required
def response_page(event_id):
    """M09 authority/admin incident-response page. Same scope rule as the hazard management API."""
    incident = db.session.get(Incident, event_id)
    if incident is None:
        abort(404)
    if not response_service.can_manage(current_user, incident):
        abort(403)
    return render_template(
        'pages/hazard_response.html', incident=incident,
        assessments=[a.to_dict() for a in risk_service.assess_incident(incident)],
        timeline=response_service.timeline(incident), actions=response_service.actions(incident),
        allowed=response_service.allowed_transitions(incident), note_required=response_service.NOTE_REQUIRED_FOR,
        action_types=ACTION_TYPES, action_statuses=ACTION_STATUSES, action_transitions=ACTION_TRANSITIONS,
        is_open=incident.status in ACTIVE_STATUSES)


@monitoring_bp.route('/api/dashboard', methods=['GET'])
@api_login_required
def dashboard_data():
    raw = request.args.get('district_id', '').strip()
    district_id = None
    if raw:
        # bounded: a 20-digit id overflowed SQLite (500) on this frequently polled endpoint (H03.10)
        if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 2**31 - 1:
            return jsonify({'error': 'district_id must be a positive integer'}), 400
        district_id = int(raw)
    try:
        payload = dashboard_service.build(current_user, district_id)
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except LookupError as e:
        return jsonify({'error': str(e)}), 404
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'private, no-store'
    return response
