from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import RoadSegment, District
from datetime import datetime

road_bp = Blueprint('roads', __name__)

@road_bp.route('/status')
@login_required
def road_status():
    """Show live road status."""
    district_id = request.args.get('district_id', '').strip()
    if not (district_id.isascii() and district_id.isdigit()):  # 'abc' used to be a 500
        district_id = ''
    
    if district_id:
        roads = RoadSegment.query.filter_by(district_id=int(district_id)).all()
    else:
        roads = RoadSegment.query.all()
    
    districts = District.query.order_by(District.name).all()
    
    return render_template('pages/road_status.html',
                         roads=roads,
                         districts=districts,
                         selected_district=district_id)
