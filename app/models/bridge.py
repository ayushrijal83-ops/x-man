from app.extensions import db
from datetime import datetime

class Bridge(db.Model):
    """Bridge model for infrastructure tracking."""
    __tablename__ = 'bridges'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    river_id = db.Column(db.Integer, db.ForeignKey('rivers.id'), nullable=True)
    road_segment_id = db.Column(db.Integer, db.ForeignKey('road_segments.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    location = db.Column(db.String(200))
    status = db.Column(db.String(20), default='open')  # open, restricted, closed, critical
    condition = db.Column(db.String(20), default='good')  # good, fair, poor, critical
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    river = db.relationship('River', backref='bridges')
    road_segment = db.relationship('RoadSegment', backref='bridges')
    
    def __repr__(self):
        return f'<Bridge {self.name}>'