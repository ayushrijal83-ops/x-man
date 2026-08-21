from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import current_user, login_required
from app.extensions import db
from app.models import District, Post, Authority, Project, RoadSegment, River, Incident

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Landing page."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('pages/landing.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard for NepalSathi."""
    user_district = None
    if current_user.district_id:
        user_district = District.query.get(current_user.district_id)
    
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(10).all()
    active_incidents = Incident.query.filter_by(status='active').limit(5).all()

    def local_first(model, limit=5):
        """Prefer the user's own district; fall back to nationwide if it has none.

        Without the district filter the page claimed 'Your District: X' while
        listing another district's roads.
        """
        if user_district:
            rows = model.query.filter_by(district_id=user_district.id).limit(limit).all()
            if rows:
                return rows, True
        return model.query.limit(limit).all(), False

    road_segments, roads_local = local_first(RoadSegment)
    rivers, rivers_local = local_first(River)
    projects, projects_local = local_first(Project)
    authorities = Authority.query.limit(5).all()

    return render_template('pages/dashboard.html',
                         user_district=user_district,
                         recent_posts=recent_posts,
                         active_incidents=active_incidents,
                         roads=road_segments,
                         rivers=rivers,
                         projects=projects,
                         authorities=authorities,
                         roads_local=roads_local,
                         rivers_local=rivers_local,
                         projects_local=projects_local)

@main_bp.route('/select-district', methods=['POST'])
@login_required
def select_district():
    """Select user's district."""
    district_id = request.form.get('district_id')
    if district_id:
        current_user.district_id = int(district_id)
        db.session.commit()
        flash('District selected successfully!', 'success')
    return redirect(url_for('main.dashboard'))

@main_bp.route('/districts')
@login_required
def districts():
    """Show all districts."""
    all_districts = District.query.order_by(District.province, District.name).all()
    
    provinces = {}
    for district in all_districts:
        if district.province not in provinces:
            provinces[district.province] = []
        provinces[district.province].append(district)
    
    return render_template('pages/districts.html', provinces=provinces)

@main_bp.route('/district/<int:district_id>')
@login_required
def district_detail(district_id):
    """District detail page."""
    district = District.query.get_or_404(district_id)
    
    posts = Post.query.filter_by(district_id=district_id).order_by(Post.created_at.desc()).limit(20).all()
    authorities = Authority.query.filter_by(district_id=district_id).all()
    projects = Project.query.filter_by(district_id=district_id).all()
    roads = RoadSegment.query.filter_by(district_id=district_id).all()
    rivers = River.query.filter_by(district_id=district_id).all()
    incidents = Incident.query.filter_by(district_id=district_id, status='active').all()
    
    return render_template('pages/district_detail.html',
                         district=district,
                         posts=posts,
                         authorities=authorities,
                         projects=projects,
                         roads=roads,
                         rivers=rivers,
                         incidents=incidents)