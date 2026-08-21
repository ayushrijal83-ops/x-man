from app.extensions import db
from datetime import datetime

class Incident(db.Model):
    """Incident model for tracking events."""
    __tablename__ = 'incidents'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    severity = db.Column(db.String(20), default='medium')
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    location = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')
    confidence = db.Column(db.Float, default=0.0)
    report_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Incident {self.id}: {self.category}>'