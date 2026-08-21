from app.extensions import db
from datetime import datetime

class District(db.Model):
    """District model for Nepal's 77 districts."""
    __tablename__ = 'districts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    province = db.Column(db.String(50), nullable=False)
    headquarters = db.Column(db.String(100))
    population = db.Column(db.Integer)
    area_sq_km = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<District {self.name}>'