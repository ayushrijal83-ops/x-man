from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from datetime import datetime

EMERGENCY_ALERT_STATES = ('not_requested', 'granted', 'denied', 'unsupported', 'disabled_by_user')

class User(UserMixin, db.Model):
    """User model for authentication and profiles."""
    __tablename__ = 'users'
    __table_args__ = (db.Index('uq_users_phone', 'phone', unique=True),)
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='citizen')
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    authority_id = db.Column(db.Integer, db.ForeignKey('authorities.id'), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)
    reputation = db.Column(db.Integer, default=0)
    language = db.Column(db.String(10), default='ne')
    bio = db.Column(db.Text)
    # E.164 mobile (account_service.normalize_mobile). Unique: prepared for future emergency SMS.
    # phone_verified stays False until a real verification flow exists (none yet).
    phone = db.Column(db.String(20))  # unique via uq_users_phone below
    phone_verified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    full_name = db.Column(db.String(120))
    permanent_address = db.Column(db.String(300))
    # Last location the user explicitly shared from their browser. Private: owner and admins only.
    current_latitude = db.Column(db.Float)
    current_longitude = db.Column(db.Float)
    current_address = db.Column(db.String(300))  # only when the user typed it (no reverse geocoding)
    location_updated_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # M12 admin control. Column overrides UserMixin.is_active: Flask-Login refuses inactive users.
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    must_change_password = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    last_login_at = db.Column(db.DateTime)
    # M12 emergency alerts: EMERGENCY_ALERT_STATES, reconciled with the browser on every visit
    emergency_alert_state = db.Column(db.String(20), nullable=False, default='not_requested',
                                      server_default='not_requested')
    emergency_sound_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # Super Admin: bumping this ends every session and remember-me cookie of the account (see get_id)
    session_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    authority = db.relationship('Authority', foreign_keys=[authority_id])
    district = db.relationship('District', foreign_keys=[district_id])
    
    def get_id(self):
        """Session identity '<id>:<session_version>'; load_user rejects any other version."""
        return f'{self.id}:{self.session_version or 0}'

    def end_sessions(self):
        self.session_version = (self.session_version or 0) + 1

    def set_password(self, password):
        """Hash and set password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password."""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'