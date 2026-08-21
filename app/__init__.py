from flask import Flask
from flask_login import current_user
import os
from dotenv import load_dotenv

load_dotenv()

def create_app(config_name=None):
    app = Flask(__name__)
    
    config_name = config_name or os.getenv('FLASK_ENV', 'development')
    from app.config import config
    app.config.from_object(config[config_name])
    
    from app.extensions import db, login_manager, csrf, migrate
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    
    from app.models.user import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
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

    @app.context_processor
    def inject_translations():
        """Expose t() / current_lang / languages to every template."""
        from flask import session
        lang = session.get('language')
        if not lang and current_user.is_authenticated:
            lang = current_user.language
        lang = lang or 'ne'
        return {
            't': lambda key: translation_service.get_translation(lang, key),
            'current_lang': lang,
            'languages': translation_service.get_supported_languages(),
        }

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response
    
    return app