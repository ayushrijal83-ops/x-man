"""Notification center (M03): /api/notifications (JSON) and /notifications (page).

Every query is scoped to current_user.id, so a user can only ever see or change
their own notifications; someone else's id is indistinguishable from a missing one (404).
Creating notifications is not exposed over HTTP — only hazard_event_service does that.
"""
import time
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric import ec
from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, session
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Incident, Notification, PushSubscription
from app.models.incident import ACTIVE_STATUSES
from app.routes.hazard_events import api_login_required
from app.services import emergency_dispatcher, notification_service, web_push

TEST_INTERVAL = 30  # seconds between test pushes per session
ACTIVE_ALERT_HOURS = 48  # in-website emergency alert only for recent, unread, still-active hazards

notifications_bp = Blueprint('notifications', __name__)


def reader_language():
    """Same rule as the page translations: session choice, then the saved preference, then Nepali."""
    return session.get('language') or (current_user.language if current_user.is_authenticated else None) or 'ne'


@notifications_bp.app_context_processor
def inject_unread_notifications():
    """Unread count for the sidebar badge, and hazard headlines in the reader's language."""
    context = {'alert_title': lambda n: notification_service.localized_title(n, reader_language())}
    if current_user.is_authenticated:
        return {**context, 'unread_notifications': notification_service.unread_count(current_user.id)}
    return {**context, 'unread_notifications': 0}


@notifications_bp.route('/notifications')
@login_required
def notification_center():
    notifications = notification_service.get_user_notifications(current_user.id, limit=100)
    return render_template('pages/notifications.html', notifications=notifications)


@notifications_bp.route('/api/notifications', methods=['GET'])
@api_login_required
def list_notifications():
    unread_only = request.args.get('unread') in ('1', 'true')
    limit = max(1, min(request.args.get('limit', 50, type=int), 200))
    items = notification_service.get_user_notifications(current_user.id, unread_only, limit)
    return jsonify({
        'notifications': [n.to_dict() for n in items],
        'unread_count': notification_service.unread_count(current_user.id),
    })


@notifications_bp.route('/api/notifications/unread-count', methods=['GET'])
@api_login_required
def get_unread_count():
    return jsonify({'unread_count': notification_service.unread_count(current_user.id)})


@notifications_bp.route('/api/notifications/<notification_id>/read', methods=['POST'])
@api_login_required
def read_notification(notification_id):
    if not (notification_id.isascii() and notification_id.isdigit()):
        return jsonify({'error': 'Invalid notification id'}), 400
    notification = notification_service.mark_as_read(current_user.id, int(notification_id))
    if not notification:
        return jsonify({'error': 'Not found'}), 404  # also for other users' ids: no existence leak
    return jsonify({'notification': notification.to_dict(),
                    'unread_count': notification_service.unread_count(current_user.id)})


@notifications_bp.route('/api/notifications/read-all', methods=['POST'])
@api_login_required
def read_all_notifications():
    updated = notification_service.mark_all_as_read(current_user.id)
    return jsonify({'updated': updated, 'unread_count': 0})


# --- M12: emergency alert preferences, Web Push subscriptions, in-website alerts ----------------
# Every route acts on current_user only: a subscription can't be attached to, listed for, tested
# against or removed from another account. Endpoints and keys are never returned.

@notifications_bp.route('/sw.js')
def service_worker():
    """Served from the site root so the worker's scope covers every page."""
    response = send_from_directory(current_app.static_folder, 'js/sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@notifications_bp.route('/notifications/settings')
@login_required
def emergency_settings():
    return render_template('pages/notification_settings.html', push=emergency_dispatcher.push_state(current_user))


@notifications_bp.route('/api/push/config', methods=['GET'])
@api_login_required
def push_config():
    return jsonify(emergency_dispatcher.push_state(current_user))


def _valid_key(value, length, prefix=None):
    if not isinstance(value, str) or len(value) > 200:
        return False
    try:
        raw = web_push.b64url_decode(value)
    except (ValueError, TypeError):
        return False
    return len(raw) == length and (prefix is None or raw[:1] == prefix)


@notifications_bp.route('/api/push/subscribe', methods=['POST'])
@api_login_required
def push_subscribe():
    if not emergency_dispatcher.push_configured():
        return jsonify({'error': 'Web Push is not configured on this server'}), 503
    data = request.get_json(silent=True)
    subscription = data.get('subscription') if isinstance(data, dict) else None
    subscription = subscription if isinstance(subscription, dict) else {}
    endpoint = subscription.get('endpoint')
    keys = subscription.get('keys') if isinstance(subscription.get('keys'), dict) else {}
    if not isinstance(endpoint, str) or not web_push.endpoint_allowed(
            endpoint, current_app.config['WEB_PUSH_ALLOWED_HOSTS']):
        return jsonify({'error': 'Unsupported push endpoint'}), 400
    p256dh, auth = keys.get('p256dh'), keys.get('auth')
    if not _valid_key(p256dh, 65, b'\x04') or not _valid_key(auth, 16):
        return jsonify({'error': 'Invalid subscription keys'}), 400
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), web_push.b64url_decode(p256dh))
    except ValueError:
        return jsonify({'error': 'Invalid subscription keys'}), 400

    row = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if row is None:
        row = PushSubscription(endpoint=endpoint)
        db.session.add(row)
    # the same browser endpoint now belongs to whoever is signed in on that browser
    row.user_id, row.p256dh_key, row.auth_key = current_user.id, p256dh, auth
    row.enabled, row.failure_count = True, 0
    row.user_agent = (request.user_agent.string or '')[:200] or None
    current_user.emergency_alert_state = 'granted'
    db.session.commit()
    return jsonify({'ok': True, 'subscription': row.summary(), **emergency_dispatcher.push_state(current_user)}), 201


@notifications_bp.route('/api/push/unsubscribe', methods=['POST'])
@api_login_required
def push_unsubscribe():
    """Turn off emergency push for this account: removes all of the user's subscriptions.
    Notification history is untouched."""
    removed = PushSubscription.query.filter_by(user_id=current_user.id).delete(synchronize_session=False)
    current_user.emergency_alert_state = 'disabled_by_user'
    db.session.commit()
    return jsonify({'ok': True, 'removed': removed, **emergency_dispatcher.push_state(current_user)})


@notifications_bp.route('/api/push/state', methods=['POST'])
@api_login_required
def push_state():
    """Browser-reported permission when this device can't or won't subscribe. 'granted' is only set
    by a real subscription; an explicit opt-out and other devices' subscriptions are not overridden."""
    data = request.get_json(silent=True)
    state = data.get('state') if isinstance(data, dict) else None
    if state not in ('not_requested', 'denied', 'unsupported'):
        return jsonify({'error': 'Invalid state'}), 400
    if current_user.emergency_alert_state != 'disabled_by_user' and \
            not current_user.push_subscriptions.filter_by(enabled=True).count():
        current_user.emergency_alert_state = state
        db.session.commit()
    return jsonify(emergency_dispatcher.push_state(current_user))


@notifications_bp.route('/api/push/test', methods=['POST'])
@api_login_required
def push_test():
    """Test push to the caller's own subscriptions only, at most once per TEST_INTERVAL seconds."""
    if not emergency_dispatcher.push_configured():
        return jsonify({'error': 'Web Push is not configured on this server'}), 503
    if time.time() - session.get('push_test_at', 0) < TEST_INTERVAL:
        return jsonify({'error': 'Please wait before sending another test'}), 429
    if not emergency_dispatcher.deliverable_subscriptions([current_user.id]):
        return jsonify({'error': 'Emergency alerts are not enabled on any device'}), 409
    session['push_test_at'] = time.time()
    sent, total = emergency_dispatcher.send_test(current_user)
    return jsonify({'sent': sent, 'devices': total})


@notifications_bp.route('/api/emergency/sound', methods=['POST'])
@api_login_required
def emergency_sound():
    data = request.get_json(silent=True)
    enabled = data.get('enabled') if isinstance(data, dict) else None
    if not isinstance(enabled, bool):
        return jsonify({'error': 'enabled must be true or false'}), 400
    current_user.emergency_sound_enabled = enabled
    db.session.commit()
    return jsonify({'sound_enabled': enabled})


@notifications_bp.route('/api/emergency/active', methods=['GET'])
@api_login_required
def active_emergencies():
    """Layer 2 feed: the caller's own unread emergency alerts for hazards that are still active."""
    since = datetime.utcnow() - timedelta(hours=ACTIVE_ALERT_HOURS)
    rows = Notification.query.join(Incident, Notification.incident_id == Incident.id).filter(
        Notification.user_id == current_user.id, Notification.is_read.is_(False),
        Notification.created_at >= since, Notification.type.in_(emergency_dispatcher.ALERT_TYPES),
        Incident.status.in_(ACTIVE_STATUSES)) \
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(20).all()
    lang = reader_language()
    alerts = [{**n.to_dict(), 'title': notification_service.localized_title(n, lang)}
              for n in rows if emergency_dispatcher.is_emergency(n.type, n.severity)][:5]
    # H03.10: the same per-page status poll also keeps the unread badge and notification lists current
    # (own notifications only; two indexed queries, nothing is written).
    latest = db.session.query(db.func.max(Notification.id)).filter(Notification.user_id == current_user.id).scalar()
    response = jsonify({'alerts': alerts, 'sound_enabled': bool(current_user.emergency_sound_enabled),
                        'unread_count': notification_service.unread_count(current_user.id),
                        'latest_notification_id': latest})
    response.headers['Cache-Control'] = 'private, no-store'
    return response

