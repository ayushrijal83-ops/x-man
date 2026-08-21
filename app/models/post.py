from app.extensions import db
from datetime import datetime

class Post(db.Model):
    """Social media post model."""
    __tablename__ = 'posts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50))
    language = db.Column(db.String(10), default='ne')
    location = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    severity = db.Column(db.String(20))
    is_ai_classified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Post {self.id} by User {self.user_id}>'