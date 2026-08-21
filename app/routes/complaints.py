from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Complaint, Authority, District
import random
from datetime import datetime

complaint_bp = Blueprint('complaints', __name__)

def generate_ticket_number(district_id):
    """Generate unique ticket number."""
    district = District.query.get(district_id)
    prefix = district.name[:3].upper() if district else 'GEN'
    year = datetime.now().year
    random_num = random.randint(1000, 9999)
    return f'{prefix}-{year}-{random_num}'

@complaint_bp.route('/')
@login_required
def list_complaints():
    """List user's complaints."""
    complaints = Complaint.query.filter_by(user_id=current_user.id).order_by(Complaint.created_at.desc()).all()
    return render_template('pages/my_complaints.html', complaints=complaints)

@complaint_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_complaint():
    """Create new complaint."""
    if request.method == 'POST':
        authority_id = request.form.get('authority_id')
        district_id = request.form.get('district_id', current_user.district_id)
        category = request.form.get('category')
        description = request.form.get('description')
        location = request.form.get('location')
        urgency = request.form.get('urgency', 'medium')
        
        if not authority_id or not description:
            flash('Authority and description are required.', 'error')
            return redirect(url_for('complaints.new_complaint'))
        
        ticket_number = generate_ticket_number(int(district_id))
        
        complaint = Complaint(
            ticket_number=ticket_number,
            user_id=current_user.id,
            authority_id=int(authority_id),
            district_id=int(district_id),
            category=category,
            description=description,
            location=location,
            urgency=urgency
        )
        
        db.session.add(complaint)
        db.session.commit()
        
        flash(f'Complaint filed successfully! Ticket: {ticket_number}', 'success')
        return redirect(url_for('complaints.list_complaints'))
    
    authorities = Authority.query.all()
    districts = District.query.order_by(District.name).all()
    return render_template('pages/file_complaint.html', 
                         authorities=authorities,
                         districts=districts)

@complaint_bp.route('/<int:complaint_id>')
@login_required
def complaint_detail(complaint_id):
    """View complaint details."""
    complaint = Complaint.query.get_or_404(complaint_id)
    return render_template('pages/complaint_detail.html', complaint=complaint)