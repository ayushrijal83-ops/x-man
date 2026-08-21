from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required, current_user
from app.services.ai_service import AIService
from app.models import Post, District, RoadSegment, River, Project, Incident

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
        'status': 'healthy' if is_healthy else 'fallback',
        'provider': ai_service.provider,
        'model': ai_service.model,
        'message': 'Ollama connected' if is_healthy else 'Using fallback classification'
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

@ai_bp.route('/test-classify')
@login_required
def test_classify():
    """Test classification page."""
    return render_template('pages/test_classify.html')

@ai_bp.route('/district-summary/<int:district_id>')
@login_required
def district_summary(district_id):
    """Generate district summary."""
    district = District.query.get_or_404(district_id)
    roads = RoadSegment.query.filter_by(district_id=district_id).all()
    rivers = River.query.filter_by(district_id=district_id).all()
    projects = Project.query.filter_by(district_id=district_id).all()
    incidents = Incident.query.filter_by(district_id=district_id, status='active').all()
    
    summary = ai_service.summarize_district(
        district.name, roads, rivers, projects, incidents
    )
    
    return jsonify({
        'district': district.name,
        'summary': summary
    })