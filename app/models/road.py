from app.extensions import db
from datetime import datetime

class RoadSegment(db.Model):
    """Road segment model for live tracking."""
    __tablename__ = 'road_segments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    highway = db.Column(db.String(100))
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    from_location = db.Column(db.String(100))
    to_location = db.Column(db.String(100))
    distance_km = db.Column(db.Float)
    status = db.Column(db.String(20), default='open')
    traffic_level = db.Column(db.String(20), default='low')
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<RoadSegment {self.name}>'

class RoadUpdate(db.Model):
    """Road update/incident model."""
    __tablename__ = 'road_updates'
    
    id = db.Column(db.Integer, primary_key=True)
    road_segment_id = db.Column(db.Integer, db.ForeignKey('road_segments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    update_type = db.Column(db.String(50))
    description = db.Column(db.Text)
    status = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<RoadUpdate {self.id}>'