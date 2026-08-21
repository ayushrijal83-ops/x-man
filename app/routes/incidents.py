from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Incident, District
from datetime import datetime

incidents_bp = Blueprint('incidents', __name__)

@incidents_bp.route('/report', methods=['GET', 'POST'])
@login_required
def report_incident():
    """Report a new incident."""
    if request.method == 'POST':
        category = request.form.get('category')
        severity = request.form.get('severity', 'medium')
        district_id = request.form.get('district_id')
        location = request.form.get('location')
        description = request.form.get('description')
        
        if not category or not description:
            flash('Category and description are required.', 'error')
            return redirect(url_for('incidents.report_incident'))
        
        incident = Incident(
            category=category,
            severity=severity,
            district_id=int(district_id) if district_id else None,
            location=location,
            description=description,
            status='active',
            confidence=0.5,
            report_count=1
        )
        
        db.session.add(incident)
        db.session.commit()
        
        flash('Incident reported successfully!', 'success')
        return redirect(url_for('main.dashboard'))
    
    districts = District.query.order_by(District.name).all()
    return render_template('pages/report_incident.html', districts=districts)

@incidents_bp.route('/active')
@login_required
def active_incidents():
    """Show active incidents."""
    incidents = Incident.query.filter_by(status='active').order_by(Incident.created_at.desc()).all()
    return render_template('pages/active_incidents.html', incidents=incidents)