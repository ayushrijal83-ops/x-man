"""Authority response records (M09): status audit trail, investigation notes, response actions.

All internal: authorities/admins responsible for the incident only, never in public serializers.
Notes and history rows are append-only (no edit/delete endpoint) so the record stays auditable.
"""
from datetime import datetime

from app.extensions import db

NOTE_MAX = 2000
ACTION_DESCRIPTION_MAX = 1000
ACTION_TYPES = ['inspect_site', 'close_road', 'evacuate_area', 'deploy_team', 'contact_local_authority',
                'place_warning', 'monitor_area', 'other']
ACTION_STATUSES = ['planned', 'in_progress', 'completed', 'cancelled']
# planned -> in_progress -> completed; planned/in_progress -> cancelled; completed/cancelled are final
ACTION_TRANSITIONS = {
    'planned': ['in_progress', 'completed', 'cancelled'],
    'in_progress': ['completed', 'cancelled'],
    'completed': [],
    'cancelled': [],
}


class IncidentStatusHistory(db.Model):
    """One row per lifecycle transition, written in the same transaction as the status change."""
    __tablename__ = 'incident_status_history'

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=False, index=True)
    previous_status = db.Column(db.String(20), nullable=False)
    new_status = db.Column(db.String(20), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # None = system
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    changed_by = db.relationship('User')

    def to_dict(self):
        return {'id': self.id, 'previous_status': self.previous_status, 'new_status': self.new_status,
                'changed_by': self.changed_by.username if self.changed_by else None, 'note': self.note,
                'created_at': self.created_at.isoformat()}


class IncidentInvestigation(db.Model):
    __tablename__ = 'incident_investigations'

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    author = db.relationship('User')

    def to_dict(self):
        return {'id': self.id, 'note': self.note, 'author': self.author.username if self.author else None,
                'created_at': self.created_at.isoformat()}


class IncidentResponseAction(db.Model):
    __tablename__ = 'incident_response_actions'

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action_type = db.Column(db.String(30), nullable=False)  # ACTION_TYPES
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='planned')  # ACTION_STATUSES
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)  # server-set when status becomes completed

    author = db.relationship('User')

    def to_dict(self):
        return {'id': self.id, 'action_type': self.action_type, 'description': self.description,
                'status': self.status, 'author': self.author.username if self.author else None,
                'created_at': self.created_at.isoformat(),
                'updated_at': self.updated_at.isoformat() if self.updated_at else None,
                'completed_at': self.completed_at.isoformat() if self.completed_at else None}
