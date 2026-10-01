from app.extensions import db
from datetime import datetime

# Hazards a citizen can report with a photo (M05). Subset of incident.HAZARD_TYPES;
# flood/earthquake come from sensors, not the camera workflow.
VISUAL_HAZARD_TYPES = ['landslide', 'road_damage']

# Report review lifecycle — separate from the Incident lifecycle.
# submitted -> accepted | rejected (by an authority/admin)
REPORT_STATUS = ['submitted', 'accepted', 'rejected']
REPORT_REVIEW_STATUSES = ['accepted', 'rejected']

# M06 vision analysis of the stored photo. Evidence for reviewers only; it never
# changes hazard_type, the report status or the Incident.
AI_STATUS = ['not_analyzed', 'completed', 'failed']
AI_LABELS = ['road_damage', 'landslide', 'unknown']


class CitizenReport(db.Model):
    """One citizen's photo evidence (M05). Evidence, not a hazard event:
    several reports can point at the same Incident."""
    __tablename__ = 'citizen_reports'

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=True, index=True)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False, index=True)

    hazard_type = db.Column(db.String(20), nullable=False)  # VISUAL_HAZARD_TYPES
    description = db.Column(db.Text)  # private: reporter + reviewers only
    location = db.Column(db.String(200))  # landmark text, becomes the public Incident.location
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    # Server-generated '<uuid4 hex>.jpg'; never a client filename or a path.
    image_filename = db.Column(db.String(64), nullable=False, unique=True)

    status = db.Column(db.String(20), nullable=False, default='submitted')  # REPORT_STATUS
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # M06: AI_STATUS / AI_LABELS. ai_confidence is the model's score, not a probability of a hazard.
    ai_status = db.Column(db.String(20), nullable=False, default='not_analyzed', server_default='not_analyzed')
    ai_label = db.Column(db.String(20))
    ai_confidence = db.Column(db.Float)
    ai_model = db.Column(db.String(100))
    ai_model_version = db.Column(db.String(64))
    ai_analyzed_at = db.Column(db.DateTime)

    reporter = db.relationship('User', foreign_keys=[reporter_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])
    incident = db.relationship('Incident', backref='citizen_reports')
    district = db.relationship('District')

    def __repr__(self):
        return f'<CitizenReport {self.id}: {self.hazard_type} ({self.status})>'

    def ai_dict(self):
        return {
            'status': self.ai_status,
            'label': self.ai_label,
            'confidence': self.ai_confidence,
            'model': self.ai_model,
            'model_version': self.ai_model_version,
            'analyzed_at': self.ai_analyzed_at.isoformat() if self.ai_analyzed_at else None,
        }

    def to_dict(self, include_reporter=False):
        """For the reporter or a reviewer only. No filesystem path, no source_reference.
        AI analysis is reviewer-only (include_reporter=True)."""
        data = {
            'id': self.id,
            'hazard_type': self.hazard_type,
            'status': self.status,
            'incident_id': self.incident_id,
            'incident_status': self.incident.status if self.incident else None,
            'district': {'id': self.district.id, 'name': self.district.name} if self.district else None,
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'description': self.description,
            'image_url': f'/api/reports/{self.id}/image',
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_reporter:
            data['reporter'] = {'username': self.reporter.username} if self.reporter else None
            data['ai_analysis'] = self.ai_dict()
        return data
