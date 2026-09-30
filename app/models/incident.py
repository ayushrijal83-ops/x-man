from app.extensions import db
from datetime import datetime

# Single source of truth for hazard-event vocabulary (M02).
# earthquake = abnormal ground/seismic motion (M03); no sensor source wired yet
HAZARD_TYPES = ['flood', 'earthquake', 'landslide', 'road_damage']
HAZARD_SOURCES = ['iot', 'citizen_report', 'authority', 'system']
HAZARD_SEVERITY = ['low', 'medium', 'high', 'critical']
HAZARD_STATUS = ['detected', 'investigating', 'confirmed', 'resolved', 'rejected']
ACTIVE_STATUSES = ['detected', 'investigating', 'confirmed']

# detected -> investigating -> confirmed -> resolved; detected/investigating -> rejected
VALID_STATUS_TRANSITIONS = {
    'detected': ['investigating', 'rejected'],
    'investigating': ['confirmed', 'rejected'],
    'confirmed': ['resolved'],
    'resolved': [],
    'rejected': [],
}


class Incident(db.Model):
    """The single hazard-event record for X-MAN (M02).

    Every source (IoT, citizen report, authority, system) produces an Incident.
    Notifications are a separate, downstream concern.
    """
    __tablename__ = 'incidents'

    id = db.Column(db.Integer, primary_key=True)

    event_type = db.Column(db.String(20), nullable=False)  # HAZARD_TYPES
    severity = db.Column(db.String(20), default='medium')  # HAZARD_SEVERITY
    source = db.Column(db.String(20), default='citizen_report')  # HAZARD_SOURCES

    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    location = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    river_id = db.Column(db.Integer, db.ForeignKey('rivers.id'), nullable=True)
    road_segment_id = db.Column(db.Integer, db.ForeignKey('road_segments.id'), nullable=True)

    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    source_reference = db.Column(db.String(100))  # e.g. device_3, user_12 (internal)

    status = db.Column(db.String(20), default='detected')  # HAZARD_STATUS
    confidence = db.Column(db.Float, nullable=True)  # only set when a real model produces one
    report_count = db.Column(db.Integer, default=1)

    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    district = db.relationship('District', backref='incidents')
    river = db.relationship('River', backref='incidents')
    road_segment = db.relationship('RoadSegment', backref='incidents')
    additional_districts = db.relationship('IncidentAffectedDistrict', back_populates='incident',
                                           order_by='IncidentAffectedDistrict.id')

    def __repr__(self):
        return f'<Incident {self.id}: {self.event_type} ({self.status})>'

    @property
    def affected_districts(self):
        """Primary district (implicit) first, then explicitly added ones."""
        districts = [self.district] if self.district else []
        return districts + [row.district for row in self.additional_districts
                            if row.district_id != self.district_id]

    @property
    def affected_district_ids(self):
        return [d.id for d in self.affected_districts]

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    def can_transition_to(self, new_status):
        return new_status in VALID_STATUS_TRANSITIONS.get(self.status, [])

    def transition_status(self, new_status):
        """Move to new_status or raise ValueError. Returns the old status. Does not commit."""
        if not self.can_transition_to(new_status):
            raise ValueError(f"Invalid transition from {self.status} to {new_status}")
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.utcnow()
        if new_status == 'resolved':
            self.resolved_at = self.updated_at
        return old_status

    def to_dict(self, include_internal=False):
        data = {
            'id': self.id,
            'event_type': self.event_type,
            'severity': self.severity,
            'source': self.source,
            'district_id': self.district_id,
            'district_name': self.district.name if self.district else None,
            'affected_districts': [{'id': d.id, 'name': d.name} for d in self.affected_districts],
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'river_id': self.river_id,
            'river_name': self.river.name if self.river else None,
            'road_segment_id': self.road_segment_id,
            'road_segment_name': self.road_segment.name if self.road_segment else None,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'confidence': self.confidence,
            'report_count': self.report_count,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_internal:
            # identifies the reporting user/device, so only authorities/admins see it
            data['source_reference'] = self.source_reference
        return data


class IncidentAffectedDistrict(db.Model):
    """An additional district affected by a hazard (M04).

    The incident's own district_id is the primary district and is always
    affected implicitly; only extra districts are stored here.
    """
    __tablename__ = 'incident_affected_districts'
    __table_args__ = (db.UniqueConstraint('incident_id', 'district_id', name='uq_incident_affected_district'),)

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    incident = db.relationship('Incident', back_populates='additional_districts')
    district = db.relationship('District')

    def __repr__(self):
        return f'<IncidentAffectedDistrict incident={self.incident_id} district={self.district_id}>'
