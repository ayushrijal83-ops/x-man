"""Citizen photo reports (M05).

Pages:  GET /report (mobile form), GET /reports/mine, GET /reports/review (authority/admin, M06)
API:    POST /api/reports (multipart), GET /api/reports, GET /api/reports/<id>,
        GET /api/reports/<id>/image, POST /api/reports/<id>/review (authority/admin),
        POST /api/reports/<id>/analyze (authority/admin, M06: re-run vision analysis)

Visibility: the reporter, admins, and authorities responsible for the report's
district. Anyone else gets 404, so report ids don't leak. Images are stored
outside /static and only served through the authorized image route.
"""
from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_file
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app.extensions import db
from app.models import CitizenReport, District
from app.models.citizen_report import REPORT_STATUS, VISUAL_HAZARD_TYPES
from app.routes.hazard_events import api_login_required, manager_required
from app.models import NodeEvidence
from app.services import citizen_report_service as reports, node_evidence_service

reports_bp = Blueprint('reports', __name__)


def _is_manager():
    return current_user.role in ('authority', 'admin')


def _serialize(report):
    return report.to_dict(include_reporter=_is_manager())


def _load_visible(report_id):
    if not (report_id.isascii() and report_id.isdigit()):
        return None, (jsonify({'error': 'Invalid report id'}), 400)
    report = db.session.get(CitizenReport, int(report_id))
    if not report or not reports.can_view(current_user, report):
        return None, (jsonify({'error': 'Not found'}), 404)
    return report, None


@reports_bp.route('/report')
@login_required
def report_page():
    districts = District.query.order_by(District.name).all()
    return render_template('pages/report_hazard.html', districts=districts, hazard_types=VISUAL_HAZARD_TYPES,
                           max_mb=reports.MAX_IMAGE_BYTES // (1024 * 1024))


@reports_bp.route('/reports/mine')
@login_required
def my_reports_page():
    mine = CitizenReport.query.filter_by(reporter_id=current_user.id) \
        .order_by(CitizenReport.created_at.desc()).limit(100).all()
    return render_template('pages/my_reports.html', reports=mine)


@reports_bp.route('/reports/review')
@login_required
def review_page():
    """Reviewer view: citizen report, AI analysis and Incident status side by side (M06)."""
    if not _is_manager():
        abort(403)
    items = reports.visible_reports_query(current_user)         .order_by(CitizenReport.created_at.desc(), CitizenReport.id.desc()).limit(100).all()
    # M-LIVE-02: camera-node field evidence of the same districts (admin: all), reviewed alongside
    evidence = node_evidence_service.visible_query(current_user) \
        .order_by(NodeEvidence.received_at.desc(), NodeEvidence.id.desc()).limit(50).all()
    return render_template('pages/review_reports.html', reports=items, evidence=evidence,
                           can_review=lambda r: reports.can_review(current_user, r))


@reports_bp.route('/api/reports', methods=['POST'])
@api_login_required
def create_report():
    """multipart/form-data: hazard_type, district_id, image, [latitude, longitude, location, description].
    Any `source`, `status`, `severity` or `incident_id` field is ignored."""
    if not (request.mimetype or '').startswith('multipart/form-data'):
        return jsonify({'error': 'Content-Type must be multipart/form-data'}), 400
    try:
        form, image = request.form, request.files.get('image')
    except RequestEntityTooLarge:
        return jsonify({'error': 'Upload is too large'}), 413
    try:
        report, created = reports.submit_report(current_user, form, image)
    except reports.ReportError as e:
        return jsonify({'error': str(e)}), e.status
    return jsonify({'report': _serialize(report), 'incident_created': created}), 201


@reports_bp.route('/api/reports', methods=['GET'])
@api_login_required
def list_reports():
    query = reports.visible_reports_query(current_user)
    status = request.args.get('status')
    if status:
        if status not in REPORT_STATUS:
            return jsonify({'error': 'Invalid status'}), 400
        query = query.filter(CitizenReport.status == status)
    limit = max(1, min(request.args.get('limit', 50, type=int), 200))
    items = query.order_by(CitizenReport.created_at.desc(), CitizenReport.id.desc()).limit(limit).all()
    return jsonify({'reports': [_serialize(r) for r in items]})


@reports_bp.route('/api/reports/<report_id>', methods=['GET'])
@api_login_required
def get_report(report_id):
    report, error = _load_visible(report_id)
    if error:
        return error
    return jsonify({'report': _serialize(report)})


@reports_bp.route('/api/reports/<report_id>/image', methods=['GET'])
@api_login_required
def get_report_image(report_id):
    report, error = _load_visible(report_id)
    if error:
        return error
    path = reports.image_path(report)
    try:
        response = send_file(path, mimetype='image/jpeg', max_age=0) if path else None
    except FileNotFoundError:
        response = None
    if response is None:
        return jsonify({'error': 'Image not available'}), 404
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Content-Disposition'] = 'inline'
    return response


@reports_bp.route('/api/reports/<report_id>/review', methods=['POST'])
@manager_required
def review(report_id):
    """Body: {"status": "accepted" | "rejected"}. Reviews the evidence only; the
    Incident lifecycle is still managed through /api/hazards."""
    report, error = _load_visible(report_id)
    if error:
        return error
    if not reports.can_review(current_user, report):
        return jsonify({'error': 'Not authorized to review this report'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON object body is required'}), 400
    try:
        reports.review_report(current_user, report, data.get('status'))
    except reports.ReportError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), e.status
    return jsonify({'report': _serialize(report)})


@reports_bp.route('/api/reports/<report_id>/analyze', methods=['POST'])
@manager_required
def analyze(report_id):
    """Re-run vision analysis on the report's stored image (e.g. after a failure or with the
    model newly installed). Updates only the report's AI evidence, never the Incident."""
    report, error = _load_visible(report_id)
    if error:
        return error
    if not reports.can_review(current_user, report):
        return jsonify({'error': 'Not authorized to analyze this report'}), 403
    if not current_app.config.get('VISION_ENABLED'):
        return jsonify({'error': 'Vision analysis is disabled'}), 503
    reports.analyze_report(report)
    return jsonify({'report': _serialize(report)})
