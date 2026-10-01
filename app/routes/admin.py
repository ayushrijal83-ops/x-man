"""Admin control center (M12): /admin/*. Admin role only, enforced server-side for every route.

Citizens and authorities get 403 (anonymous users are sent to log in). Lookups by id 404 when the
id is not of the expected role, so the citizen pages can't be used to browse authority/admin users.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db, login_manager
from app.models import Authority, District, User
from app.models.user import EMERGENCY_ALERT_STATES
from app.services import admin_service

admin_bp = Blueprint('admin', __name__)


@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if current_user.role != 'admin':
        abort(403)


def _int_arg(name, default=None, minimum=0):
    raw = (request.args.get(name) or '').strip()
    if raw.isascii() and raw.isdigit() and int(raw) >= minimum:
        return int(raw)
    return default


def _filters(statuses):
    status = request.args.get('status')
    return {'district_id': _int_arg('district_id'), 'q': (request.args.get('q') or '').strip()[:100],
            'status': status if status in statuses else None, 'page': _int_arg('page', 1, minimum=1)}


@admin_bp.route('')
def home():
    return render_template('admin/home.html', o=admin_service.overview())


@admin_bp.route('/citizens')
def citizens():
    f = _filters(admin_service.ACCOUNT_STATUSES)
    pagination, push_counts = admin_service.citizens(**f)
    return render_template('admin/citizens.html', f=f, pagination=pagination, push_counts=push_counts,
                           district_counts=admin_service.district_citizen_counts(),
                           selected=db.session.get(District, f['district_id']) if f['district_id'] else None,
                           districts=District.query.order_by(District.name).all())


@admin_bp.route('/citizens/<int:user_id>')
def citizen_detail(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role != 'citizen':
        abort(404)
    return render_template('admin/citizen_detail.html', user=user, d=admin_service.citizen_detail(user))


@admin_bp.route('/authorities')
def authorities():
    f = _filters(admin_service.AUTHORITY_STATUSES)
    pagination, rows = admin_service.authorities(**f)
    return render_template('admin/authorities.html', f=f, pagination=pagination, rows=rows,
                           districts=District.query.order_by(District.name).all())


@admin_bp.route('/authorities/<int:authority_id>')
def authority_detail(authority_id):
    authority = db.session.get(Authority, authority_id)
    if authority is None:
        abort(404)
    return render_template('admin/authority_detail.html', authority=authority,
                           d=admin_service.authority_detail(authority))


@admin_bp.route('/notifications')
def notifications():
    return render_template('admin/notifications.html', s=admin_service.notification_status(),
                           states=EMERGENCY_ALERT_STATES)


def _managed_user(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role not in ('citizen', 'authority'):
        abort(404)
    return user


def _back(user):
    if user.role == 'authority' and user.authority_id:
        return redirect(url_for('admin.authority_detail', authority_id=user.authority_id))
    if user.role == 'citizen':
        return redirect(url_for('admin.citizen_detail', user_id=user.id))
    return redirect(url_for('admin.authorities'))


@admin_bp.route('/users/<int:user_id>/status', methods=['POST'])
def set_status(user_id):
    user = _managed_user(user_id)
    active = request.form.get('active')
    if active not in ('0', '1'):
        abort(400)
    try:
        admin_service.set_active(current_user, user, active == '1')
        flash(f'Account {user.username} {"enabled" if active == "1" else "disabled"}.', 'success')
    except PermissionError as e:
        flash(str(e), 'error')
    return _back(user)


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
def reset_password(user_id):
    user = _managed_user(user_id)
    try:
        admin_service.reset_password(current_user, user, request.form.get('temporary_password'),
                                     request.form.get('confirm_password'))
        flash(f'Temporary password set for {user.username}. They must change it at next login.', 'success')
    except (PermissionError, ValueError) as e:
        flash(str(e), 'error')
    return _back(user)
