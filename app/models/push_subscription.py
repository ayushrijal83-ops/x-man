from datetime import datetime

from app.extensions import db


class PushSubscription(db.Model):
    """One browser's Web Push subscription (M12). Always owned by the user who created it.

    endpoint is a capability URL and p256dh/auth are the browser's encryption keys: none of them
    is ever rendered or returned by an API. The server's VAPID private key is not stored here.
    """
    __tablename__ = 'push_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(1000), nullable=False, unique=True)
    p256dh_key = db.Column(db.String(200), nullable=False)
    auth_key = db.Column(db.String(100), nullable=False)
    user_agent = db.Column(db.String(200))
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime)
    failure_count = db.Column(db.Integer, nullable=False, default=0)

    user = db.relationship('User', backref=db.backref('push_subscriptions', lazy='dynamic'))

    def summary(self):
        """Safe metadata for the owner/admin: no endpoint, no keys."""
        return {'id': self.id, 'enabled': self.enabled, 'device': self.user_agent or 'Unknown browser',
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None}
