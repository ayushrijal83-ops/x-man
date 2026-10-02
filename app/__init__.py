from flask import Flask
from flask_login import current_user
from jinja2 import pass_context
import os
from dotenv import load_dotenv

load_dotenv()

def create_app(config_name=None):
    app = Flask(__name__)

    config_name = config_name or os.getenv('FLASK_ENV', 'development')
    from app.config import config, DEFAULT_SECRET_KEY
    app.config.from_object(config[config_name])
    if config_name == 'production' and app.config.get('SECRET_KEY') in (None, '', DEFAULT_SECRET_KEY):
        # M10: never run production with the public development key (session/CSRF forgery)
        raise RuntimeError('SECRET_KEY must be set in the environment for production')

    from app.extensions import db, login_manager, csrf, migrate
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        # '<id>:<session_version>'; a bare '<id>' (sessions from before versioning) counts as version 0
        uid, _, version = str(user_id).partition(':')
        version = version or '0'
        if not (uid.isascii() and uid.isdigit() and version.isascii() and version.isdigit()):
            return None
        user = db.session.get(User, int(uid))
        if user is None or not user.is_active or int(version) != (user.session_version or 0):
            return None  # M12: disabling ends sessions; Super Admin: so does a session_version bump
        return user

    from flask import jsonify as _jsonify, redirect as _redirect, request as _request, url_for as _url_for

    @app.before_request
    def require_password_change():
        """M12: after an admin reset, the temporary password only opens the change-password page."""
        if current_user.is_authenticated and current_user.must_change_password and _request.endpoint not in (
                'profile.change_password', 'auth.logout', 'static'):
            if _request.path.startswith('/api/'):
                return _jsonify({'error': 'Password change required'}), 403
            return _redirect(_url_for('profile.change_password'))

    # Register all blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.api import api_bp
    from app.routes.posts import post_bp
    from app.routes.complaints import complaint_bp
    from app.routes.roads import road_bp
    from app.routes.rivers import rivers_bp
    from app.routes.projects import projects_bp
    from app.routes.authorities import authorities_bp
    from app.routes.travel import travel_bp
    from app.routes.ai_routes import ai_bp
    from app.routes.authority_panel import authority_panel_bp
    from app.routes.profile import profile_bp
    from app.routes.social import social_bp
    from app.routes.language import language_bp
    from app.routes.iot import iot_bp
    from app.routes.hazard_events import hazard_events_bp
    from app.routes.notifications import notifications_bp
    from app.routes.reports import reports_bp
    from app.routes.monitoring import monitoring_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(post_bp, url_prefix='/posts')
    app.register_blueprint(complaint_bp, url_prefix='/complaints')
    app.register_blueprint(road_bp, url_prefix='/roads')
    app.register_blueprint(rivers_bp, url_prefix='/rivers')
    app.register_blueprint(projects_bp, url_prefix='/projects')
    app.register_blueprint(authorities_bp, url_prefix='/authorities')
    app.register_blueprint(travel_bp, url_prefix='/travel')
    app.register_blueprint(ai_bp, url_prefix='/ai')
    app.register_blueprint(authority_panel_bp, url_prefix='/authority')
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(social_bp, url_prefix='/social')
    app.register_blueprint(language_bp, url_prefix='/language')
    app.register_blueprint(iot_bp)
    app.register_blueprint(hazard_events_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.services.translation_service import TranslationService
    translation_service = TranslationService()

    @app.template_filter('metres')
    def _metres(value):
        """Render a water level, or a dash when it is unknown.

        Rivers confirmed by OpenStreetMap have no gauge reading, and
        '{{ none }}m' was rendering as 'Nonem' on the dashboard.
        """
        if value is None:
            return '—'
        return '%.1fm' % value

    def active_language():
        """Session language, else the user's saved preference, else Nepali."""
        from flask import session
        lang = session.get('language')
        if not lang and current_user.is_authenticated:
            lang = current_user.language
        return lang or 'ne'

    @app.template_filter('t')
    @pass_context
    def _t(_ctx, text):
        """Translate page content: {{ 'Road Status'|t }}.

        pass_context is load-bearing: without it Jinja constant-folds
        `'Road Status'|t` when the template is first compiled and every later
        request keeps that first visitor's language.
        """
        return translation_service.get_translation(active_language(), text)

    @app.cli.command('push-keys')
    def push_keys():
        """Print a new VAPID key pair for .env (M12 Web Push). Keep the private key secret."""
        from app.services.web_push import generate_vapid_keys
        public, private = generate_vapid_keys()
        print(f'VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}\nVAPID_SUBJECT=mailto:you@example.org')

    from app.image_credits import IMAGE_CREDITS

    @app.context_processor
    def inject_image_credits():
        return {'image_credits': IMAGE_CREDITS}

    @app.context_processor
    def inject_translations():
        """Expose t() / current_lang / languages to every template."""
        lang = active_language()
        return {
            't': lambda key: translation_service.get_translation(lang, key),
            'current_lang': lang,
            'languages': translation_service.get_supported_languages(),
        }

    from datetime import datetime
    from flask import jsonify, request
    from werkzeug.exceptions import HTTPException
    from app.extensions import RUNTIME

    @app.teardown_request
    def rollback_failed_request(error):
        """M11: a request that raised must not leave flushed-but-uncommitted rows in the session.
        Flask-SQLAlchemy rolls back when the app context ends; this also covers code that keeps one
        app context across several requests (tests, scripts)."""
        if error is not None:
            db.session.rollback()
            db.session.info.pop('emergency_push_outbox', None)  # M12: never push rolled-back alerts

    @app.errorhandler(HTTPException)
    def api_errors_as_json(error):
        """M10: /api/* errors (404, 405, 413, CSRF 400, 500...) are short JSON, never HTML pages or
        tracebacks. Other paths keep Flask's standard error pages."""
        if error.code and error.code >= 500:
            RUNTIME['server_errors'] += 1
            RUNTIME['last_server_error_at'] = datetime.utcnow()
        if request.path.startswith('/api/'):
            message = error.description if error.code < 500 else 'Internal server error'
            return jsonify({'error': message}), error.code
        return error

    # Pages use inline scripts/styles and onclick handlers, so script-src needs 'unsafe-inline';
    # the policy still pins every external origin and blocks plugins, framing and base hijacking.
    csp = '; '.join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https://unpkg.com https://*.tile.openstreetmap.org",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ])

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(self), geolocation=(self), microphone=()'
        response.headers['Content-Security-Policy'] = csp
        return response

    return app