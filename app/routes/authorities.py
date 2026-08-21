from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models import Authority, District

authorities_bp = Blueprint('authorities', __name__)

@authorities_bp.route('/directory')
@login_required
def directory():
    """Authority directory page."""
    district_id = request.args.get('district_id')
    
    if district_id:
        authorities = Authority.query.filter_by(district_id=int(district_id)).all()
    else:
        authorities = Authority.query.all()
    
    districts = District.query.order_by(District.name).all()
    
    return render_template('pages/authority_directory.html',
                         authorities=authorities,
                         districts=districts,
                         selected_district=district_id)