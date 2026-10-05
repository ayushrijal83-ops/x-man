import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SECRET_KEY = 'dev-key-change-me'  # development only; production refuses to start with it (M10)


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', DEFAULT_SECRET_KEY)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///hackforge.db')
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # M10: public authority sign-up creates a verified authority with manager rights over a
    # district, so it is off unless explicitly enabled (e.g. a local demo). Admins create accounts.
    AUTHORITY_SELF_REGISTRATION = os.getenv('AUTHORITY_SELF_REGISTRATION', 'false').lower() == 'true'

    # M06 vision analysis (see docs/PROJECT_PROGRESS.md). Local files only, no API key.
    VISION_ENABLED = os.getenv('VISION_ENABLED', 'true').lower() == 'true'
    VISION_MODEL_NAME = 'google/siglip-base-patch16-224'
    VISION_MODEL_REVISION = '7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed'
    VISION_MODEL_PATH = os.getenv('VISION_MODEL_PATH', os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'models', 'siglip-base-patch16-224'))
    # Must stay > 0.5 so a hazard label always means "the majority of the prompt mass".
    VISION_CONFIDENCE_THRESHOLD = float(os.getenv('VISION_CONFIDENCE_THRESHOLD', '0.6'))

    # M08 abnormal-motion rule (MPU6050-class prototype). Unset = rule disabled: no validated
    # thresholds exist until the real node is characterized (hardware milestones).
    MOTION_VIBRATION_THRESHOLD_MG = float(os.environ['MOTION_VIBRATION_THRESHOLD_MG']) \
        if os.getenv('MOTION_VIBRATION_THRESHOLD_MG') else None
    MOTION_TILT_CHANGE_THRESHOLD_DEG = float(os.environ['MOTION_TILT_CHANGE_THRESHOLD_DEG']) \
        if os.getenv('MOTION_TILT_CHANGE_THRESHOLD_DEG') else None

    # Seismic device-event state machine (Phase 1). Pure in-memory tracking of one device's
    # abnormal-motion episode. Does not create incidents or notifications.
    MOTION_RECOVERY_WINDOWS = int(os.getenv('MOTION_RECOVERY_WINDOWS', '3'))
    MOTION_GAP_TOLERANCE_SECONDS = int(os.getenv('MOTION_GAP_TOLERANCE_SECONDS', '300'))

    # M-LIVE-02 camera-node field evidence (POST /api/iot/evidence). Engineering defaults, not validated
    # field values: a mounted phone should sit within NODE_MAX_DISTANCE_KM of its registered location.
    NODE_MAX_DISTANCE_KM = float(os.getenv('NODE_MAX_DISTANCE_KM', '1.0'))
    NODE_MAX_GPS_ACCURACY_M = float(os.getenv('NODE_MAX_GPS_ACCURACY_M', '50'))
    NODE_MAX_GPS_FIX_AGE_SECONDS = int(os.getenv('NODE_MAX_GPS_FIX_AGE_SECONDS', '300'))  # fix older than capture
    NODE_MAX_EVIDENCE_AGE_HOURS = int(os.getenv('NODE_MAX_EVIDENCE_AGE_HOURS', '72'))  # older: held, no new event
    NODE_MAX_EVIDENCE_PER_HOUR = int(os.getenv('NODE_MAX_EVIDENCE_PER_HOUR', '6'))  # confirmed events, not frames
    NODE_HOLD_AFTER_REJECTION_HOURS = int(os.getenv('NODE_HOLD_AFTER_REJECTION_HOURS', '24'))
    EVIDENCE_UPLOAD_DIR = os.getenv('EVIDENCE_UPLOAD_DIR')  # default: instance/uploads/evidence

    # M12 Web Push. Server credentials from the environment only (generate with `flask push-keys`);
    # unset = push disabled, in-app and in-website alerts still work. The private key never reaches a page.
    VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '')
    VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
    VAPID_SUBJECT = os.getenv('VAPID_SUBJECT', 'mailto:admin@x-man.local')
    # The server POSTs to subscription endpoints, so only these push services are accepted (no SSRF).
    WEB_PUSH_ALLOWED_HOSTS = [h.strip().lower() for h in os.getenv(
        'WEB_PUSH_ALLOWED_HOSTS',
        'fcm.googleapis.com,updates.push.services.mozilla.com,push.services.mozilla.com,'
        'notify.windows.com,push.apple.com').split(',') if h.strip()]
    # Lowest hazard severity that raises the in-website emergency alert and an emergency push.
    # An unknown value falls back to 'high' (never to "everything is an emergency").
    EMERGENCY_MIN_SEVERITY = os.getenv('EMERGENCY_MIN_SEVERITY', 'high').strip().lower()
    if EMERGENCY_MIN_SEVERITY not in ('low', 'medium', 'high', 'critical'):
        EMERGENCY_MIN_SEVERITY = 'high'

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False
    ENV = 'development'

class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    VISION_ENABLED = False  # M06 tests enable it with a stub classifier
    # Tests assume shipped defaults, not the developer's local .env (tests set these explicitly)
    MOTION_VIBRATION_THRESHOLD_MG = None
    MOTION_TILT_CHANGE_THRESHOLD_DEG = None
    EMERGENCY_MIN_SEVERITY = 'high'

class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'

config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}