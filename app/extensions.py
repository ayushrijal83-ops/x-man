from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()

login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"
# Super Admin system health: per-process counters since start (never contain request data or secrets).
# ponytail: in-memory, resets on restart and is per worker; persist to a table if multi-worker totals matter
RUNTIME = {'telemetry_rejected_auth': 0, 'telemetry_rejected_invalid': 0, 'last_telemetry_rejected_at': None,
           'server_errors': 0, 'last_server_error_at': None}
