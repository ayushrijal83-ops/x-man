import os
os.environ['FLASK_APP'] = 'run.py'
os.environ['FLASK_ENV'] = 'development'
os.environ['SECRET_KEY'] = '85e05de9dbe09e639acc960aca2035835d1eda80f4005ac76923c65e8fef655d'
os.environ['DATABASE_URL'] = 'sqlite:///instance/hackforge.db'
os.environ['AI_PROVIDER'] = 'ollama'
os.environ['AI_MODEL'] = 'qwen2.5:0.5b'
os.environ['OLLAMA_URL'] = 'http://localhost:11434'

from app import create_app
from app.services.emergency_dispatcher import is_emergency, _threshold, ALERT_TYPES
from app.models.incident import HAZARD_SEVERITY

app = create_app()
with app.app_context():
    print("EMERGENCY_MIN_SEVERITY config:", app.config.get('EMERGENCY_MIN_SEVERITY'))
    print("HAZARD_SEVERITY:", HAZARD_SEVERITY)
    print("ALERT_TYPES:", ALERT_TYPES)
    print("_threshold():", _threshold())
    print()
    print("is_emergency('hazard_detected', 'medium'):", is_emergency('hazard_detected', 'medium'))
    print("is_emergency('hazard_confirmed', 'medium'):", is_emergency('hazard_confirmed', 'medium'))
    print("is_emergency('hazard_detected', 'high'):", is_emergency('hazard_detected', 'high'))
    print("is_emergency('hazard_escalated', 'medium'):", is_emergency('hazard_escalated', 'medium'))