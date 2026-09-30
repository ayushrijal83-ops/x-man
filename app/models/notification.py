from app.extensions import db
from datetime import datetime

# Hazard lifecycle notifications (M03). One vocabulary for every hazard type.
NOTIFICATION_TYPES = ['hazard_detected', 'hazard_escalated', 'hazard_confirmed', 'hazard_resolved', 'system',
                      'report_update']  # report_update: status of the user's own citizen report (M05)
# Written by pre-M03 code; kept readable so legacy rows still display.
LEGACY_NOTIFICATION_TYPES = ['road_alert', 'river_alert', 'project_update', 'complaint_response']


class Notification(db.Model):
    """Notification model for user alerts."""
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notifications_user_read', 'user_id', 'is_read'),
        # M04: final defence against duplicate alerts. NULL keys (legacy rows,
        # non-hazard notifications) are not compared, so old data is untouched.
        db.Index('uq_notifications_user_dedup', 'user_id', 'dedup_key', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # NOTIFICATION_TYPES (+ legacy)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(200))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # M03: which hazard event this is about, and the severity at the time it was sent
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=True, index=True)
    severity = db.Column(db.String(20), nullable=True)  # HAZARD_SEVERITY
    # M04: '<incident_id>:<type>' or '<incident_id>:hazard_escalated:<severity>'
    dedup_key = db.Column(db.String(80), nullable=True)

    # Relationships
    user = db.relationship('User', backref='notifications')
    incident = db.relationship('Incident')

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id}>'

    def to_dict(self):
        """Safe for the owner: no reporter/device identifiers, no other users."""
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'link': self.link,
            'severity': self.severity,
            'is_read': bool(self.is_read),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'hazard': {
                'id': self.incident.id,
                'event_type': self.incident.event_type,
                'status': self.incident.status,
                'district_name': self.incident.district.name if self.incident.district else None,
                'affected_districts': [d.name for d in self.incident.affected_districts],
            } if self.incident else None,
        }
