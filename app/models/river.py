from app.extensions import db
from datetime import datetime

class River(db.Model):
    """River model for status monitoring."""
    __tablename__ = 'rivers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    current_level = db.Column(db.Float)
    danger_level = db.Column(db.Float)
    status = db.Column(db.String(20), default='normal')
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<River {self.name}>'

class RiverUpdate(db.Model):
    """River update model."""
    __tablename__ = 'river_updates'
    
    id = db.Column(db.Integer, primary_key=True)
    river_id = db.Column(db.Integer, db.ForeignKey('rivers.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    water_level = db.Column(db.Float)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<RiverUpdate {self.id}>'