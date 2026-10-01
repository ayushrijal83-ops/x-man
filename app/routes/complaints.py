from flask import Blueprint, abort, render_template, redirect, url_for, request, flash
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Complaint, Authority, District
import secrets
from datetime import datetime

from app.services.form_validation import int_in_range

complaint_bp = Blueprint('complaints', __name__)

CATEGORIES = ['road_blocked', 'water_supply', 'electricity', 'waste', 'landslide', 'bridge', 'drainage', 'other']
URGENCIES = ['low', 'medium', 'high', 'critical']
MAX_DESCRIPTION = 5000


def generate_ticket_number(district):
    """Unique ticket like SIN-2026-7F3A9C. Was 4 random digits under a unique index: with ~100
    complaints per district per year a collision (and a 500) was roughly a coin flip."""
    prefix = district.name[:3].upper()
    while True:
        ticket = f'{prefix}-{datetime.now().year}-{secrets.token_hex(3).upper()}'
        if not Complaint.query.filter_by(ticket_number=ticket).first():
            return ticket

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
        authority = db.session.get(Authority, int_in_range(request.form.get('authority_id'), 1, 2**31) or 0)
        district = db.session.get(District, int_in_range(
            request.form.get('district_id', current_user.district_id), 1, 2**31) or 0)
        category = request.form.get('category')
        urgency = request.form.get('urgency', 'medium')
        description = (request.form.get('description') or '').strip()
        location = (request.form.get('location') or '').strip()[:200] or None

        # M10-style validation: unknown ids, values outside the form's options and empty text are
        # user errors, not 500s or rows pointing at nothing
        if (authority is None or district is None or not description or category not in CATEGORIES
                or urgency not in URGENCIES or len(description) > MAX_DESCRIPTION):
            flash('Choose a district, an authority and a category, and describe the issue.', 'error')
            return redirect(url_for('complaints.new_complaint'))

        ticket_number = generate_ticket_number(district)
        complaint = Complaint(
            ticket_number=ticket_number,
            user_id=current_user.id,
            authority_id=authority.id,
            district_id=district.id,
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
    complaint = db.session.get(Complaint, complaint_id)
    # M10: only the complainant, the authority it was filed to, or an admin (was: any logged-in user)
    allowed = complaint is not None and (
        complaint.user_id == current_user.id or current_user.role == 'admin'
        or (current_user.role == 'authority' and current_user.authority_id is not None
            and complaint.authority_id == current_user.authority_id))
    if not allowed:
        abort(404)
    return render_template('pages/complaint_detail.html', complaint=complaint)