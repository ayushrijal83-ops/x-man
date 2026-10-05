import os
os.environ['FLASK_APP'] = 'run.py'
os.environ['FLASK_ENV'] = 'development'
os.environ['SECRET_KEY'] = '85e05de9dbe09e639acc960aca2035835d1eda80f4005ac76923c65e8fef655d'
os.environ['DATABASE_URL'] = 'sqlite:///instance/hackforge.db'
os.environ['AI_PROVIDER'] = 'ollama'
os.environ['AI_MODEL'] = 'qwen2.5:0.5b'
os.environ['OLLAMA_URL'] = 'http://localhost:11434'

from app import create_app
from app.config import Config

app = create_app()
with app.app_context():
    print("MOTION_VIBRATION_THRESHOLD_MG:", app.config.get('MOTION_VIBRATION_THRESHOLD_MG'))
    print("MOTION_TILT_CHANGE_THRESHOLD_DEG:", app.config.get('MOTION_TILT_CHANGE_THRESHOLD_DEG'))
    print("EMERGENCY_MIN_SEVERITY:", app.config.get('EMERGENCY_MIN_SEVERITY'))