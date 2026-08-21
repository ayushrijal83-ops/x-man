from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import RoadSegment, RoadUpdate, District
from datetime import datetime

road_bp = Blueprint('roads', __name__)

@road_bp.route('/status')
@login_required
def road_status():
    """Show live road status."""
    district_id = request.args.get('district_id')
    
    if district_id:
        roads = RoadSegment.query.filter_by(district_id=int(district_id)).all()
    else:
        roads = RoadSegment.query.all()
    
    districts = District.query.order_by(District.name).all()
    
    return render_template('pages/road_status.html',
                         roads=roads,
                         districts=districts,
                         selected_district=district_id)

@road_bp.route('/<int:road_id>')
@login_required
def road_detail(road_id):
    """Road detail page."""
    road = RoadSegment.query.get_or_404(road_id)
    updates = RoadUpdate.query.filter_by(road_segment_id=road_id).order_by(RoadUpdate.created_at.desc()).all()
    return render_template('pages/road_detail.html', road=road, updates=updates)