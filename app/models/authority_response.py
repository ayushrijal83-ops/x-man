from app.extensions import db
from datetime import datetime

class AuthorityResponse(db.Model):
    """Authority response model for complaints."""
    __tablename__ = 'authority_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=False)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status_update = db.Column(db.String(20))  # pending, in_progress, resolved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    complaint = db.relationship('Complaint', backref='responses')
    authority = db.relationship('Authority', backref='responses')
    
    def __repr__(self):
        return f'<AuthorityResponse {self.id} for Complaint {self.complaint_id}>'