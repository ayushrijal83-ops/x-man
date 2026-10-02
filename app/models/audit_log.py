"""Super Admin audit trail. Append-only: the ORM refuses to update or delete a row, and no route edits one.

Never store credentials here: summaries are built by admin_service from safe fields only
(usernames, device ids, statuses). `reason` is the operator's own free text.
"""
from datetime import datetime

from sqlalchemy import event

from app.extensions import db

REASON_MAX = 500
AUDIT_ACTIONS = [
    'DISABLED_USER', 'ENABLED_USER', 'RESET_PASSWORD', 'FORCED_PASSWORD_CHANGE', 'TERMINATED_SESSIONS',
    'DISABLED_AUTHORITY', 'ENABLED_AUTHORITY',
    'DISABLED_DEVICE', 'ENABLED_DEVICE', 'ROTATED_DEVICE_KEY', 'REGISTERED_DEVICE', 'UPDATED_DEVICE',
    'CHANGED_HAZARD_STATUS', 'REVIEWED_REPORT', 'DISABLED_PUSH_SUBSCRIPTION',
]
AUDIT_TARGETS = ['user', 'authority', 'device', 'hazard', 'report', 'push_subscription']


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    # actor snapshot: the row stays readable even if the account is renamed later
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    actor_username = db.Column(db.String(80), nullable=False)
    actor_role = db.Column(db.String(20), nullable=False)
    action = db.Column(db.String(40), nullable=False, index=True)  # AUDIT_ACTIONS
    target_type = db.Column(db.String(30), nullable=False)  # AUDIT_TARGETS
    target_id = db.Column(db.String(64), nullable=False)
    target_label = db.Column(db.String(200))
    reason = db.Column(db.String(REASON_MAX), nullable=False)
    summary = db.Column(db.String(500))
    success = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (db.Index('ix_audit_logs_target', 'target_type', 'target_id'),)

    def __repr__(self):
        return f'<AuditLog {self.id} {self.action} {self.target_type}:{self.target_id}>'


@event.listens_for(AuditLog, 'before_update')
@event.listens_for(AuditLog, 'before_delete')
def _append_only(mapper, connection, target):
    raise PermissionError('Audit log entries are append-only')
