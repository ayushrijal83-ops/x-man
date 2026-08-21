from flask import Blueprint, jsonify
from datetime import datetime

api_bp = Blueprint('api', __name__)

@api_bp.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'checks': {
            'application': {
                'status': 'healthy',
                'message': 'Application is running'
            }
        },
        'timestamp': datetime.utcnow().isoformat()
    })

@api_bp.route('/version')
def version():
    return jsonify({
        'version': '1.0.0',
        'name': 'HackForge',
        'status': 'active'
    })