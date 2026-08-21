from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import River, RiverUpdate, District
from datetime import datetime

rivers_bp = Blueprint('rivers', __name__)

@rivers_bp.route('/status')
@login_required
def river_status():
    """Show river status."""
    district_id = request.args.get('district_id')
    
    if district_id:
        rivers = River.query.filter_by(district_id=int(district_id)).all()
    else:
        rivers = River.query.all()
    
    districts = District.query.order_by(District.name).all()
    
    return render_template('pages/river_status.html',
                         rivers=rivers,
                         districts=districts,
                         selected_district=district_id)

@rivers_bp.route('/<int:river_id>/update', methods=['POST'])
@login_required
def update_river(river_id):
    """Update river status."""
    river = River.query.get_or_404(river_id)
    
    water_level = request.form.get('water_level')
    description = request.form.get('description')
    
    if water_level:
        water_level = float(water_level)
        river.current_level = water_level
        
        if river.danger_level:
            if water_level >= river.danger_level:
                river.status = 'flooding'
            elif water_level >= river.danger_level * 0.8:
                river.status = 'high'
            elif water_level >= river.danger_level * 0.6:
                river.status = 'rising'
            else:
                river.status = 'normal'
    
    update = RiverUpdate(
        river_id=river_id,
        user_id=current_user.id,
        water_level=water_level if water_level else None,
        description=description
    )
    
    river.last_updated = datetime.utcnow()
    
    db.session.add(update)
    db.session.commit()
    
    flash('River status updated successfully!', 'success')
    return redirect(url_for('rivers.river_status'))