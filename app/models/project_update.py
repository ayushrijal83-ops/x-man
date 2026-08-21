from app.extensions import db
from datetime import datetime

class ProjectUpdate(db.Model):
    """Project update model for tracking progress."""
    __tablename__ = 'project_updates'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'), nullable=True)
    update_type = db.Column(db.String(50))  # photo, progress, budget, milestone, delay, general
    description = db.Column(db.Text)
    progress_percent = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref='updates')
    authority = db.relationship('Authority', backref='project_updates')
    
    def __repr__(self):
        return f'<ProjectUpdate {self.id} for Project {self.project_id}>'