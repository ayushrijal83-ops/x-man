from datetime import datetime

from app.extensions import db

# M-LIVE-02: field evidence uploaded by a camera_node device (future Android field node).
# Evidence, not a hazard event: it is attached to an Incident through hazard_event_service.
#   received  stored, not yet attached (transient inside the upload request)
#   attached  linked to a new or existing landslide Incident
#   held      stored for review only, no Incident opened (stale/future capture time, or the
#             node's last event was rejected recently): see node_evidence_service
EVIDENCE_STATUS = ['received', 'attached', 'held']
HOLD_REASONS = ['stale_capture', 'future_capture', 'after_rejection']
EVIDENCE_REVIEW_STATUS = ['submitted', 'accepted', 'rejected']  # same vocabulary as CitizenReport

# GPS validation result. Only 'accepted' lets the phone's coordinates into the Incident; otherwise
# the registered node location is used (or none). The district always comes from the device.
GPS_STATUS = ['accepted', 'missing', 'inaccurate', 'stale_fix', 'outside_radius', 'no_reference']
LOCATION_SOURCES = ['gps', 'registered', 'district']
MAX_FRAMES = 3


class NodeEvidence(db.Model):
    __tablename__ = 'node_evidence'
    __table_args__ = (db.UniqueConstraint('device_id', 'client_event_id', name='uq_node_evidence_device_event'),)

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('iot_devices.id'), nullable=False, index=True)
    # opaque, client-generated idempotency key: never used for authorization
    client_event_id = db.Column(db.String(64), nullable=False)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=True, index=True)
    # snapshot of the device's provisioned district (server-owned), for visibility checks
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False, index=True)

    captured_at = db.Column(db.DateTime, nullable=False)  # device clock, untrusted
    gps_fix_at = db.Column(db.DateTime)  # device/GPS clock, untrusted
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)  # server clock

    latitude = db.Column(db.Float)  # as reported by the phone, even when not trusted
    longitude = db.Column(db.Float)
    gps_accuracy_m = db.Column(db.Float)
    gps_status = db.Column(db.String(20), nullable=False)  # GPS_STATUS
    location_source = db.Column(db.String(20), nullable=False)  # LOCATION_SOURCES

    # untrusted device metadata: shown to reviewers, never used for severity/status/targeting
    device_score = db.Column(db.Float)
    device_model = db.Column(db.String(100))
    device_model_version = db.Column(db.String(64))
    app_version = db.Column(db.String(32))
    battery_pct = db.Column(db.Float)
    network_type = db.Column(db.String(20))

    # server-generated '<uuid4 hex>.jpg' names, comma separated, frame order kept (max MAX_FRAMES)
    frame_filenames = db.Column(db.String(200), nullable=False)

    status = db.Column(db.String(20), nullable=False, default='received')  # EVIDENCE_STATUS
    hold_reason = db.Column(db.String(30))  # HOLD_REASONS
    review_status = db.Column(db.String(20), nullable=False, default='submitted')  # EVIDENCE_REVIEW_STATUS
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)

    # server-side vision corroboration (same fields and meaning as CitizenReport, M06)
    ai_status = db.Column(db.String(20), nullable=False, default='not_analyzed')
    ai_label = db.Column(db.String(20))
    ai_confidence = db.Column(db.Float)
    ai_model = db.Column(db.String(100))
    ai_model_version = db.Column(db.String(64))
    ai_analyzed_at = db.Column(db.DateTime)

    device = db.relationship('IoTDevice', backref=db.backref('evidence', lazy='dynamic'))
    incident = db.relationship('Incident', backref='node_evidence')
    district = db.relationship('District')
    reviewed_by = db.relationship('User')

    def __repr__(self):
        return f'<NodeEvidence {self.id}: device {self.device_id} ({self.status})>'

    @property
    def frames(self):
        return [name for name in (self.frame_filenames or '').split(',') if name]
