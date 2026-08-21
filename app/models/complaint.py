from app.extensions import db
from datetime import datetime

class Complaint(db.Model):
    """Complaint/issue filing system model."""
    __tablename__ = 'complaints'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200))
    urgency = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(20), default='pending')
    government_response = db.Column(db.Text)
    resolution_details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Complaint {self.ticket_number}>'