"""Super Admin Control Center: /admin/*. Admin role only, enforced server-side for every route.

The `admin` role is the Super Admin (the highest application role); there is no separate login:
admins sign in through the existing, CSRF-protected session login. Citizens and authorities get
403 (anonymous users are sent to log in). Lookups by id 404 when the id is not of the expected
role, so the citizen pages can't be used to browse authority/admin users.

Every state-changing action needs a reason (and a typed phrase for the dangerous ones) and writes
an AuditLog row, success or failure. Nothing here renders password hashes, device key hashes,
push endpoints/keys or the VAPID private key.
"""
from flask import (Blueprint, abort, flash, jsonify, make_response, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user

from app.extensions import db, login_manager
from app.models import Authority, CitizenReport, District, Incident, IoTDevice, Notification, PushSubscription, User
from app.models.audit_log import AUDIT_ACTIONS, AUDIT_TARGETS, REASON_MAX
from app.models.citizen_report import REPORT_REVIEW_STATUSES, REPORT_STATUS, VISUAL_HAZARD_TYPES
from app.models.incident import HAZARD_SEVERITY, HAZARD_TYPES
from app.models.user import EMERGENCY_ALERT_STATES
from app.services import admin_service

admin_bp = Blueprint('admin', __name__)

# typed confirmations for the high-impact actions
PHRASES = {'user': 'DISABLE ACCOUNT', 'authority': 'DISABLE AUTHORITY', 'device': 'DISABLE DEVICE',
           'rotate': 'ROTATE KEY', 'hazard': 'CHANGE HAZARD STATUS'}


@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if current_user.role != 'admin':
        abort(403)


@admin_bp.context_processor
def inject_phrases():
    return {'PHRASES': PHRASES}


def _int_arg(name, default=None, minimum=0):
    raw = (request.args.get(name) or '').strip()
    if raw.isascii() and raw.isdigit() and int(raw) >= minimum:
        return int(raw)
    return default


def _choice(name, allowed):
    value = request.args.get(name)
    return value if value in allowed else None


def _filters(statuses):
    return {'district_id': _int_arg('district_id'), 'q': (request.args.get('q') or '').strip()[:100],
            'status': _choice('status', statuses), 'page': _int_arg('page', 1, minimum=1)}


def _districts():
    return District.query.order_by(District.name).all()


def _get(model, pk):
    obj = db.session.get(model, pk)
    if obj is None:
        abort(404)
    return obj


def _act(action, target_type, target_id, label, work, success_message, phrase=None):
    """Validate reason (+ typed phrase), run `work(reason)`, audit the outcome, commit. Returns success.

    `work` mutates and returns a safe summary, or raises PermissionError/ValueError: the change is
    rolled back and the refusal itself is audited."""
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('A reason is required. It is recorded in the audit log.', 'error')
        return False
    if len(reason) > REASON_MAX:
        flash(f'The reason must be at most {REASON_MAX} characters.', 'error')
        return False
    if phrase and (request.form.get('confirm') or '').strip() != phrase:
        flash(f'Confirmation did not match. Type {phrase} to continue.', 'error')
        return False
    try:
        summary = work(reason)
    except (PermissionError, ValueError) as e:
        db.session.rollback()
        admin_service.record(current_user, action, target_type, target_id, label, reason, str(e), success=False)
        db.session.commit()
        flash(str(e), 'error')
        return False
    admin_service.record(current_user, action, target_type, target_id, label, reason, summary)
    db.session.commit()
    flash(success_message, 'success')
    return True


# --- dashboard / overview pages -----------------------------------------------

@admin_bp.route('')
def home():
    return render_template('admin/home.html', o=admin_service.dashboard())


@admin_bp.route('/users')
def users():
    return render_template('admin/users.html', u=admin_service.users_overview())


@admin_bp.route('/health')
def health():
    return render_template('admin/health.html', h=admin_service.system_health(), iot=admin_service.iot_summary())


@admin_bp.route('/audit')
def audit():
    f = {'q': (request.args.get('q') or '').strip()[:100], 'action': _choice('action', AUDIT_ACTIONS),
         'target_type': _choice('target_type', AUDIT_TARGETS),
         'outcome': _choice('outcome', admin_service.AUDIT_OUTCOMES), 'page': _int_arg('page', 1, minimum=1)}
    return render_template('admin/audit.html', f=f, pagination=admin_service.audit_entries(**f),
                           actions=AUDIT_ACTIONS, targets=AUDIT_TARGETS)


# --- citizens -----------------------------------------------------------------

@admin_bp.route('/citizens')
def citizens():
    f = _filters(admin_service.ACCOUNT_STATUSES)
    pagination, push_counts, report_counts = admin_service.citizens(**f)
    return render_template('admin/citizens.html', f=f, pagination=pagination, push_counts=push_counts,
                           report_counts=report_counts, district_counts=admin_service.district_citizen_counts(),
                           selected=db.session.get(District, f['district_id']) if f['district_id'] else None,
                           districts=_districts())


@admin_bp.route('/citizens/<int:user_id>')
def citizen_detail(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role != 'citizen':
        abort(404)
    return render_template('admin/citizen_detail.html', user=user, d=admin_service.citizen_detail(user))


# --- authorities --------------------------------------------------------------

@admin_bp.route('/authorities')
def authorities():
    f = _filters(admin_service.AUTHORITY_STATUSES)
    pagination, rows = admin_service.authorities(**f)
    return render_template('admin/authorities.html', f=f, pagination=pagination, rows=rows, districts=_districts())


@admin_bp.route('/authorities/<int:authority_id>')
def authority_detail(authority_id):
    authority = _get(Authority, authority_id)
    return render_template('admin/authority_detail.html', authority=authority,
                           d=admin_service.authority_detail(authority))


@admin_bp.route('/authorities/<int:authority_id>/status', methods=['POST'])
def authority_status(authority_id):
    authority = _get(Authority, authority_id)
    active = request.form.get('active')
    if active not in ('0', '1'):
        abort(400)
    _act('ENABLED_AUTHORITY' if active == '1' else 'DISABLED_AUTHORITY', 'authority', authority.id,
         f'Authority: {authority.name}',
         lambda reason: admin_service.set_authority_active(current_user, authority, active == '1'),
         f'Authority {authority.name} {"reactivated" if active == "1" else "deactivated"}.',
         phrase=PHRASES['authority'] if active == '0' else None)
    return redirect(url_for('admin.authority_detail', authority_id=authority.id))


# --- account actions (citizen or authority accounts) ---------------------------

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


def _user_label(user):
    return f'User: @{user.username} ({user.role})'


@admin_bp.route('/users/<int:user_id>/status', methods=['POST'])
def set_status(user_id):
    user = _managed_user(user_id)
    active = request.form.get('active')
    if active not in ('0', '1'):
        abort(400)
    _act('ENABLED_USER' if active == '1' else 'DISABLED_USER', 'user', user.id, _user_label(user),
         lambda reason: admin_service.set_active(current_user, user, active == '1'),
         f'Account {user.username} {"enabled" if active == "1" else "disabled"}.',
         phrase=PHRASES['user'] if active == '0' else None)
    return _back(user)


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
def reset_password(user_id):
    user = _managed_user(user_id)
    _act('RESET_PASSWORD', 'user', user.id, _user_label(user),
         lambda reason: admin_service.reset_password(current_user, user, request.form.get('temporary_password'),
                                                     request.form.get('confirm_password')),
         f'Temporary password set for {user.username}. They must change it at next login.')
    return _back(user)


@admin_bp.route('/users/<int:user_id>/force-password-change', methods=['POST'])
def force_password_change(user_id):
    user = _managed_user(user_id)
    _act('FORCED_PASSWORD_CHANGE', 'user', user.id, _user_label(user),
         lambda reason: admin_service.force_password_change(current_user, user),
         f'{user.username} must change their password.')
    return _back(user)


@admin_bp.route('/users/<int:user_id>/end-sessions', methods=['POST'])
def end_sessions(user_id):
    user = _managed_user(user_id)
    _act('TERMINATED_SESSIONS', 'user', user.id, _user_label(user),
         lambda reason: admin_service.terminate_sessions(current_user, user),
         f'All sessions of {user.username} were ended.')
    return _back(user)


# --- IoT devices --------------------------------------------------------------

@admin_bp.route('/devices')
def devices():
    f = _filters(admin_service.DEVICE_STATES)
    sensors = admin_service.sensor_types()
    f['sensor_type'] = _choice('sensor_type', sensors)
    pagination = admin_service.devices(**f)
    return render_template('admin/devices.html', f=f, pagination=pagination, sensors=sensors,
                           states=admin_service.device_states(pagination.items), districts=_districts(),
                           summary=admin_service.iot_summary())


@admin_bp.route('/devices/status.json')
def device_status():
    """Polled by /admin/devices every 30 s: derived UI state only, nothing is written."""
    return jsonify({'states': {str(k): v for k, v in admin_service.device_states(IoTDevice.query.all()).items()}})


def _device_page(device, new_key=None):
    hours = _int_arg('hours')
    sensor_type = (request.args.get('sensor_type') or '').strip()[:50] or None
    f = {'device_id': device.id, 'sensor_type': sensor_type,
         'hours': hours if hours in admin_service.TELEMETRY_WINDOWS else None, 'page': _int_arg('page', 1, minimum=1)}
    return render_template('admin/device_detail.html', device=device, f=f, new_key=new_key,
                           windows=admin_service.TELEMETRY_WINDOWS,
                           d=admin_service.device_detail(device, f['sensor_type'], f['hours'], f['page']))


ONE_TIME_KEY_SESSION = 'one_time_key'  # '<device pk>:<lookup token>', never the key itself


@admin_bp.route('/devices/<int:device_id>')
def device_detail(device_id):
    """Read-only: a GET never rotates or changes a key. Right after a rotation it shows the new key
    once (taken from admin_service's one-time store); any later GET, reload or back/forward can't."""
    device = _get(IoTDevice, device_id)
    pending = session.get(ONE_TIME_KEY_SESSION) or ''
    new_key = None
    if pending.partition(':')[0] == str(device.id):
        session.pop(ONE_TIME_KEY_SESSION)
        new_key = admin_service.take_one_time_key(pending.partition(':')[2], current_user.id, device.id)
    response = make_response(_device_page(device, new_key=new_key))
    if new_key:
        response.headers['Cache-Control'] = 'no-store'  # back/forward must not replay it from cache
    return response


@admin_bp.route('/devices/<int:device_id>/status', methods=['POST'])
def device_enable(device_id):
    device = _get(IoTDevice, device_id)
    enabled = request.form.get('enabled')
    if enabled not in ('0', '1'):
        abort(400)
    _act('ENABLED_DEVICE' if enabled == '1' else 'DISABLED_DEVICE', 'device', device.id, device.device_id,
         lambda reason: admin_service.set_device_enabled(current_user, device, enabled == '1'),
         'Device connected: authenticated telemetry is accepted again.' if enabled == '1'
         else 'Device disabled by Super Admin: its telemetry is now refused.',
         phrase=PHRASES['device'] if enabled == '0' else None)
    return redirect(url_for('admin.device_detail', device_id=device.id))


@admin_bp.route('/devices/<int:device_id>/rotate-key', methods=['POST'])
def device_rotate_key(device_id):
    """Post/Redirect/Get: rotate (reason + typed phrase, audited), keep the plaintext only in the
    server-side one-time store, redirect to the device page, which shows it once. Reloading that page
    is a plain GET and cannot rotate again. The key never goes into a flash, the session cookie, a
    URL, the database or a log."""
    device = _get(IoTDevice, device_id)
    issued = {}

    def work(reason):
        issued['key'], summary = admin_service.rotate_device_key(current_user, device)
        return summary

    if _act('ROTATED_DEVICE_KEY', 'device', device.id, device.device_id, work,
            'New API key generated. The previous key no longer works.', phrase=PHRASES['rotate']):
        token = admin_service.stash_one_time_key(current_user.id, device.id, issued.pop('key'))
        session[ONE_TIME_KEY_SESSION] = f'{device.id}:{token}'
    return redirect(url_for('admin.device_detail', device_id=device.id))


# --- hazards ------------------------------------------------------------------

@admin_bp.route('/hazards')
def hazards():
    f = _filters(admin_service.HAZARD_STATUS_FILTERS)
    f.update(event_type=_choice('event_type', HAZARD_TYPES), severity=_choice('severity', HAZARD_SEVERITY))
    pagination, rows = admin_service.hazards(**f)
    return render_template('admin/hazards.html', f=f, pagination=pagination, rows=rows, districts=_districts(),
                           statuses=admin_service.HAZARD_STATUS_FILTERS, types=HAZARD_TYPES,
                           severities=HAZARD_SEVERITY)


@admin_bp.route('/hazards/<int:incident_id>')
def hazard_detail(incident_id):
    incident = _get(Incident, incident_id)
    return render_template('admin/hazard_detail.html', h=incident, d=admin_service.hazard_detail(incident))


@admin_bp.route('/hazards/<int:incident_id>/status', methods=['POST'])
def hazard_status(incident_id):
    incident = _get(Incident, incident_id)
    new_status = request.form.get('status') or ''
    _act('CHANGED_HAZARD_STATUS', 'hazard', incident.id,
         f'Hazard #{incident.id}: {incident.event_type} ({incident.status})',
         lambda reason: admin_service.change_hazard_status(current_user, incident, new_status, reason),
         f'Hazard #{incident.id} moved to {new_status}.', phrase=PHRASES['hazard'])
    return redirect(url_for('admin.hazard_detail', incident_id=incident.id))


# --- citizen reports ----------------------------------------------------------

@admin_bp.route('/reports')
def reports():
    f = _filters(REPORT_STATUS)
    f.update(hazard_type=_choice('hazard_type', VISUAL_HAZARD_TYPES), ai=_choice('ai', admin_service.REPORT_AI_FILTERS))
    return render_template('admin/reports.html', f=f, pagination=admin_service.reports(**f), districts=_districts(),
                           statuses=REPORT_STATUS, types=VISUAL_HAZARD_TYPES, ai_filters=admin_service.REPORT_AI_FILTERS,
                           r=admin_service.report_overview())


@admin_bp.route('/reports/<int:report_id>/review', methods=['POST'])
def report_review(report_id):
    report = _get(CitizenReport, report_id)
    status = request.form.get('status')
    if status not in REPORT_REVIEW_STATUSES:
        abort(400)
    _act('REVIEWED_REPORT', 'report', report.id, f'Report #{report.id} ({report.hazard_type})',
         lambda reason: admin_service.review_report(current_user, report, status),
         f'Report #{report.id} {status}.')
    return redirect(url_for('admin.reports', status='submitted'))


# --- notifications / Web Push -------------------------------------------------

@admin_bp.route('/notifications')
def notifications():
    return render_template('admin/notifications.html', s=admin_service.notification_status(),
                           states=EMERGENCY_ALERT_STATES, p=admin_service.push_overview(),
                           unread=Notification.query.filter_by(is_read=False).count())


@admin_bp.route('/push')
def push():
    f = {'q': (request.args.get('q') or '').strip()[:100],
         'status': _choice('status', admin_service.SUBSCRIPTION_STATUSES), 'page': _int_arg('page', 1, minimum=1)}
    return render_template('admin/push.html', f=f, pagination=admin_service.subscriptions(**f),
                           p=admin_service.push_overview(), failures=admin_service.recent_push_failures())


@admin_bp.route('/push/<int:subscription_id>/disable', methods=['POST'])
def push_disable(subscription_id):
    subscription = _get(PushSubscription, subscription_id)
    _act('DISABLED_PUSH_SUBSCRIPTION', 'push_subscription', subscription.id,
         f'Subscription #{subscription.id} of @{subscription.user.username}',
         lambda reason: admin_service.disable_subscription(current_user, subscription),
         'Push subscription disabled. The browser can subscribe again from its settings page.')
    return redirect(url_for('admin.push', status='failing') if subscription.failure_count else url_for('admin.push'))
