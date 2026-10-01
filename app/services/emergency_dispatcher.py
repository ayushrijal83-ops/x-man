"""Emergency notification dispatcher (M12): the delivery layers on top of M03/M04 notifications.

    hazard event (hazard_event_service, source of truth)
      -> notification_service.notify_hazard   layer 1: Notification rows (targeting + per-user dedup)
      -> queue()                               only rows notify_hazard actually created
      -> flush() after the hazard commit       layer 3: Web Push to the recipients' subscriptions
    Layer 2 (in-website alert + sound) reads the same rows via GET /api/emergency/active.
    A future SMS channel would be a second sender inside _deliver; none exists yet.

No new targeting or dedup: a push is sent only for a notification row that was just created, so
repeated evidence (no new row) sends nothing and an escalation (new row per severity) sends again.
Delivery is best-effort and runs after the hazard is committed: a failed push never rolls back
or blocks the hazard. Nothing is pushed for a transaction that was rolled back.
"""
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import Notification, PushSubscription, User
from app.models.incident import HAZARD_SEVERITY
from app.services import web_push

OUTBOX = 'emergency_push_outbox'
ALERT_TYPES = ('hazard_detected', 'hazard_escalated', 'hazard_confirmed')
MAX_FAILURES = 5  # consecutive non-expiry failures before a subscription is switched off


def _rank(severity):
    return HAZARD_SEVERITY.index(severity) if severity in HAZARD_SEVERITY else -1


def _threshold():
    # unknown threshold -> 'critical' only: a bad setting must not turn every alert into an alarm
    rank = _rank(current_app.config.get('EMERGENCY_MIN_SEVERITY'))
    return rank if rank >= 0 else len(HAZARD_SEVERITY) - 1


def is_emergency(ntype, severity):
    """Active-hazard alert at or above EMERGENCY_MIN_SEVERITY: in-website alarm + urgent push."""
    return ntype in ALERT_TYPES and _rank(severity) >= _threshold()


def pushable(ntype, severity):
    """Emergency alerts, plus the all-clear for a hazard that was emergency-level."""
    return is_emergency(ntype, severity) or (
        ntype == 'hazard_resolved' and _rank(severity) >= _threshold())


def push_configured():
    config = current_app.config
    return bool(config.get('VAPID_PUBLIC_KEY') and config.get('VAPID_PRIVATE_KEY'))


def push_state(user):
    """What the browser needs to reconcile: never includes the private key or any endpoint."""
    configured = push_configured()
    return {
        'configured': configured,
        'public_key': current_app.config['VAPID_PUBLIC_KEY'] if configured else None,
        'state': user.emergency_alert_state,
        'sound_enabled': bool(user.emergency_sound_enabled),
        'subscriptions': user.push_subscriptions.filter_by(enabled=True).count(),
    }


def queue(notifications):
    """Remember freshly created notifications; delivered by flush() once the caller commits."""
    db.session.info.setdefault(OUTBOX, []).extend(
        (n.id, n.user_id, n.dedup_key) for n in notifications if pushable(n.type, n.severity))


def discard():
    """The transaction was rolled back: its notifications don't exist, so nothing is pushed."""
    db.session.info.pop(OUTBOX, None)


def payload_for(notification):
    """Public fields only (the notification title/message never contain private data). The headline
    is in the recipient's saved language; the device shows it while X-MAN is closed."""
    from app.services.notification_service import localized_title  # circular at import time
    from app.services.page_strings import page_translation
    emergency = is_emergency(notification.type, notification.severity)
    lang = (notification.user.language if notification.user else None) or 'ne'
    prefix = page_translation(lang, 'X-MAN EMERGENCY ALERT') + ': ' if emergency else 'X-MAN: '
    return {
        'title': prefix + localized_title(notification, lang),
        'body': notification.message or '',
        'url': notification.link or '/notifications',
        'tag': f'xman-hazard-{notification.incident_id}' if notification.incident_id else 'xman',
        'severity': notification.severity,
        'emergency': emergency,
        'notification_id': notification.id,
    }


def _send(subscription, payload):
    """One push. Expired endpoints (404/410) are switched off; never logs endpoint or keys."""
    status = web_push.send(subscription.endpoint, subscription.p256dh_key, subscription.auth_key, payload,
                           current_app.config, urgency='high' if payload['emergency'] else 'normal')
    if 200 <= status < 300:
        subscription.last_used_at = datetime.utcnow()
        subscription.failure_count = 0
        return True
    subscription.failure_count = (subscription.failure_count or 0) + 1
    if status in (404, 410) or subscription.failure_count >= MAX_FAILURES:
        subscription.enabled = False
        current_app.logger.info('Push subscription %s disabled (status %s)', subscription.id, status)
    else:
        current_app.logger.warning('Push to subscription %s failed (status %s)', subscription.id, status)
    return False


def deliverable_subscriptions(user_ids):
    """Enabled subscriptions of active users who opted in (state 'granted')."""
    if not user_ids:
        return []
    return PushSubscription.query.join(User, PushSubscription.user_id == User.id).filter(
        PushSubscription.user_id.in_(user_ids), PushSubscription.enabled.is_(True),
        User.is_active.is_(True), User.emergency_alert_state == 'granted').all()


def _deliver(items):
    wanted = set(items)
    notifications = [n for n in Notification.query.filter(Notification.id.in_([i[0] for i in items]))
                     if (n.id, n.user_id, n.dedup_key) in wanted]
    by_user = {}
    for subscription in deliverable_subscriptions({n.user_id for n in notifications}):
        by_user.setdefault(subscription.user_id, []).append(subscription)
    sent = 0
    # ponytail: synchronous, one POST per subscription inside the hazard request; move to a worker
    # queue when recipient counts make the request slow (each POST is capped at web_push.TIMEOUT_SECONDS)
    for notification in notifications:
        payload = payload_for(notification)
        sent += sum(_send(s, payload) for s in by_user.get(notification.user_id, []))
    db.session.commit()
    return sent


def flush():
    """Deliver queued pushes. Call right after the hazard commit. Never raises."""
    items = db.session.info.pop(OUTBOX, [])
    if not items or not push_configured():
        return 0
    try:
        return _deliver(items)
    except Exception as e:  # best-effort: the hazard is already committed
        db.session.rollback()
        current_app.logger.error('Emergency push dispatch failed: %s', type(e).__name__)
        return 0


def send_test(user):
    """Test push to the user's own subscriptions only. Returns (sent, total)."""
    subscriptions = deliverable_subscriptions([user.id])
    payload = {'title': 'X-MAN test notification', 'body': 'Emergency alerts are working on this device.',
               'url': '/notifications/settings', 'tag': 'xman-test', 'severity': None, 'emergency': False,
               'notification_id': None}
    sent = sum(_send(s, payload) for s in subscriptions)
    db.session.commit()
    return sent, len(subscriptions)
