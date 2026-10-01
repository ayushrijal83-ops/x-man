from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import District
from app.routes.auth import _safe_next
from app.services import district_service, emergency_dispatcher

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Landing page."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('pages/landing.html', stats=district_service.public_stats())


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Citizen home: the user's district, their alerts and their reports (real counts only)."""
    districts = District.query.order_by(District.name).all() if not current_user.district_id else []
    return render_template('pages/dashboard.html', home=district_service.citizen_home(current_user),
                           districts=districts, push=emergency_dispatcher.push_state(current_user))


@main_bp.route('/select-district', methods=['POST'])
@login_required
def select_district():
    """Save the user's home district. Before this milestone no page called this route and it
    crashed on an unimported flash(), so 'selecting' a district never stuck."""
    raw = (request.form.get('district_id') or '').strip()
    district = db.session.get(District, int(raw)) if raw.isascii() and raw.isdigit() else None
    if district is None:
        flash('Choose a valid district.', 'error')
    else:
        current_user.district_id = district.id
        db.session.commit()
        flash('Your district is now set.', 'success')
    return redirect(_safe_next(request.form.get('next')) or url_for('main.dashboard'))


@main_bp.route('/districts')
@login_required
def districts():
    """All districts grouped by province."""
    provinces = {}
    for district in District.query.order_by(District.province, District.name):
        provinces.setdefault(district.province, []).append(district)
    return render_template('pages/districts.html', provinces=provinces)


@main_bp.route('/district/<int:district_id>')
@login_required
def district_detail(district_id):
    """Public information for one district: hazards, rivers, roads, projects, authorities."""
    district = db.session.get(District, district_id)
    if district is None:
        abort(404)
    return render_template('pages/district_detail.html', o=district_service.district_overview(district))


@main_bp.route('/credits')
def credits():
    """Photo attribution (CC BY / CC BY-SA require it)."""
    return render_template('pages/credits.html')
