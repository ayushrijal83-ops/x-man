from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
from app.services.ai_service import AIService

ai_bp = Blueprint('ai', __name__)
ai_service = AIService()

@ai_bp.route('/assistant')
@login_required
def assistant():
    """AI Assistant page."""
    return render_template('pages/ai_assistant.html')

@ai_bp.route('/classify', methods=['POST'])
@login_required
def classify():
    """Classify a post using AI."""
    content = request.json.get('content', '')
    
    if not content:
        return jsonify({'error': 'Content required'}), 400
    
    result = ai_service.classify_post(content)
    return jsonify(result)

@ai_bp.route('/health')
@login_required
def health():
    """Check AI service health."""
    is_healthy = ai_service.health_check()
    return jsonify({
        'status': 'healthy' if is_healthy else 'unavailable',
        'model': ai_service.model
    })

@ai_bp.route('/generate', methods=['POST'])
@login_required
def generate():
    """Generate AI response."""
    prompt = request.json.get('prompt', '')
    
    if not prompt:
        return jsonify({'error': 'Prompt required'}), 400
    
    response = ai_service.generate(prompt)
    return jsonify({'response': response})