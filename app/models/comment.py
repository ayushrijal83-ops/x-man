from app.extensions import db
from datetime import datetime

class Comment(db.Model):
    """Comment model for posts and projects."""
    __tablename__ = 'comments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaints.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='comments')
    
    def __repr__(self):
        return f'<Comment {self.id} by User {self.user_id}>'