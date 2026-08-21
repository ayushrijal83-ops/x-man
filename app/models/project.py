from app.extensions import db
from datetime import datetime

class Project(db.Model):
    """Development project tracking model."""
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    category = db.Column(db.String(50))
    description = db.Column(db.Text)
    location = db.Column(db.String(200))
    total_budget = db.Column(db.Float)
    spent_budget = db.Column(db.Float)
    progress_percent = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='on_schedule')
    contractor = db.Column(db.String(200))
    start_date = db.Column(db.DateTime)
    expected_completion = db.Column(db.DateTime)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Project {self.name}>'