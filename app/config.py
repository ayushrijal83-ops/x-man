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