from flask import Blueprint, abort, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import River, RiverUpdate, District
from datetime import datetime

from app.services.form_validation import finite_float
from app.services.risk_engine import compute_river_status

rivers_bp = Blueprint('rivers', __name__)

@rivers_bp.route('/status')
@login_required
def river_status():
    """Show river status."""
    district_id = request.args.get('district_id', '').strip()
    if not (district_id.isascii() and district_id.isdigit()):  # 'abc' used to be a 500
        district_id = ''

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
    river = db.get_or_404(River, river_id)
    # M10: was open to any logged-in user; now admins and authorities of the river's district
    authority = current_user.authority if current_user.role == 'authority' else None
    if not (current_user.role == 'admin' or (authority is not None and authority.district_id == river.district_id)):
        abort(403)

    water_level = request.form.get('water_level')
    description = request.form.get('description')

    if water_level:
        water_level = finite_float(water_level, 0, 50)  # metres, same range as telemetry
        if water_level is None:
            flash('Water level must be a number from 0 to 50 m.', 'error')
            return redirect(url_for('rivers.river_status'))
        river.current_level = water_level
        if river.danger_level:
            # M10: same M01 thresholds as telemetry (was a divergent 60%/80% 'high' scale)
            river.status = compute_river_status(water_level, river.danger_level)

    update = RiverUpdate(
        river_id=river_id,
        user_id=current_user.id,
        water_level=water_level if water_level not in (None, '') else None,  # 0 m is a reading
        description=description
    )

    river.last_updated = datetime.utcnow()

    db.session.add(update)
    db.session.commit()

    flash('River status updated successfully!', 'success')
    return redirect(url_for('rivers.river_status'))