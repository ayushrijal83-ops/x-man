from flask import Flask
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
    
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response
    
    return app