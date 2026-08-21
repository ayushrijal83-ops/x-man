from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.models import District, Post, Authority, RoadSegment, River, Project, Incident, Complaint

district_bp = Blueprint('district', __name__)

@district_bp.route('/districts')
@login_required
def list_districts():
    """List all districts."""
    districts = District.query.order_by(District.province, District.name).all()
    return render_template('pages/districts.html', districts=districts)

@district_bp.route('/district/<int:district_id>')
@login_required
def district_detail(district_id):
    """District detail page."""
    district = District.query.get_or_404(district_id)
    
    # Get district data
    posts = Post.query.filter_by(district_id=district_id).order_by(Post.created_at.desc()).limit(20).all()
    authorities = Authority.query.filter_by(district_id=district_id).all()
    roads = RoadSegment.query.filter_by(district_id=district_id).all()
    rivers = River.query.filter_by(district_id=district_id).all()
    projects = Project.query.filter_by(district_id=district_id).all()
    incidents = Incident.query.filter_by(district_id=district_id, status='active').all()
    
    return render_template('pages/district_detail.html',
                         district=district,
                         posts=posts,
                         authorities=authorities,
                         roads=roads,
                         rivers=rivers,
                         projects=projects,
                         incidents=incidents)

@district_bp.route('/api/districts')
@login_required
def api_districts():
    """API endpoint for districts."""
    districts = District.query.all()
    return jsonify([{
        'id': d.id,
        'name': d.name,
        'province': d.province
    } for d in districts])