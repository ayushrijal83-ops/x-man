from app.extensions import db
from datetime import datetime

class Like(db.Model):
    """Like model for posts."""
    __tablename__ = 'likes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='likes')
    post = db.relationship('Post', backref='likes')
    
    def __repr__(self):
        return f'<Like {self.id} by User {self.user_id}>'