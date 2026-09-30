"""Notification center (M03): /api/notifications (JSON) and /notifications (page).

Every query is scoped to current_user.id, so a user can only ever see or change
their own notifications; someone else's id is indistinguishable from a missing one (404).
Creating notifications is not exposed over HTTP — only hazard_event_service does that.
"""
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.routes.hazard_events import api_login_required
from app.services import notification_service

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.app_context_processor
def inject_unread_notifications():
    """Unread count for the sidebar badge."""
    if current_user.is_authenticated:
        return {'unread_notifications': notification_service.unread_count(current_user.id)}
    return {'unread_notifications': 0}


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

