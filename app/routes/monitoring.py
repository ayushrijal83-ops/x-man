"""Disaster Monitoring Dashboard (M07).

Page: GET /monitoring            (any logged-in user; content depends on role)
API:  GET /api/dashboard[?district_id=<id>]   (district_id: admins only)

Read-only. The page polls the API; all scoping happens in dashboard_service.
"""
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.models import District
from app.routes.hazard_events import api_login_required
from app.services import dashboard_service

monitoring_bp = Blueprint('monitoring', __name__)

POLL_SECONDS = 30


@monitoring_bp.route('/monitoring')
@login_required
def monitoring_page():
    districts = District.query.order_by(District.name).all() if current_user.role == 'admin' else []
    return render_template('pages/monitoring.html', poll_seconds=POLL_SECONDS, districts=districts,
                           is_manager=dashboard_service.is_manager(current_user))


@monitoring_bp.route('/api/dashboard', methods=['GET'])
@api_login_required
def dashboard_data():
    raw = request.args.get('district_id', '').strip()
    district_id = None
    if raw:
        if not (raw.isascii() and raw.isdigit()) or int(raw) < 1:
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
