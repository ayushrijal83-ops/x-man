from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Post, Complaint, District, Like, Comment
from sqlalchemy.exc import IntegrityError

from app.services import account_service

profile_bp = Blueprint('profile', __name__)

@profile_bp.route('/<int:user_id>')
@login_required
def view_profile(user_id):
    """View user profile."""
    user = User.query.get_or_404(user_id)
    
    # Get user stats
    posts = Post.query.filter_by(user_id=user_id).order_by(Post.created_at.desc()).all()
    complaints = Complaint.query.filter_by(user_id=user_id).all()
    district = District.query.get(user.district_id) if user.district_id else None
    
    # Calculate stats
    total_posts = len(posts)
    total_complaints = len(complaints)
    resolved_complaints = len([c for c in complaints if c.status == 'resolved'])
    
    # Calculate reputation
    reputation = user.reputation or 0
    
    # Get badges
    badges = []
    if total_posts >= 5:
        badges.append('📝 Active Contributor')
    if total_posts >= 20:
        badges.append('⭐ Trusted Reporter')
    if resolved_complaints >= 3:
        badges.append('🏛️ Civic Engaged')
    if user.is_verified:
        badges.append('✓ Verified')
    if user.role == 'authority':
        badges.append('🏛️ Government')
    
    return render_template('pages/profile.html',
                         user=user,
                         posts=posts[:10],
                         complaints=complaints[:5],
                         district=district,
                         total_posts=total_posts,
                         total_complaints=total_complaints,
                         resolved_complaints=resolved_complaints,
                         reputation=reputation,
                         badges=badges)

@profile_bp.route('/me')
@login_required
def my_profile():
    """View own profile."""
    return redirect(url_for('profile.view_profile', user_id=current_user.id))

@profile_bp.route('/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit profile information."""
    districts = District.query.order_by(District.name).all()
    if request.method == 'POST':
        changes, errors = account_service.validate_profile_update(current_user, request.form, User, District, db)
        if errors:
            return render_template('pages/edit_profile.html', districts=districts, errors=errors,
                                   form=request.form), 400
        account_service.apply_profile_update(current_user, changes)
        try:
            db.session.commit()
        except IntegrityError:  # uniqueness race on username/email/mobile
            db.session.rollback()
            return render_template('pages/edit_profile.html', districts=districts, form=request.form,
                                   errors={'form': 'That username, email or mobile number was just taken.'}), 400
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile.my_profile'))

    return render_template('pages/edit_profile.html', districts=districts, errors={}, form=None)

@profile_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password. Also the only page open after an admin reset (must_change_password, M12)."""
    error = None
    if request.method == 'POST':
        current_password = request.form.get('current_password') or ''
        new_password = request.form.get('new_password') or ''
        if not current_user.check_password(current_password):
            error = 'Current password is incorrect.'
        elif new_password != request.form.get('confirm_password'):
            error = 'New passwords do not match.'
        elif len(new_password) < account_service.MIN_PASSWORD:
            error = 'Password must be at least 8 characters.'
        elif new_password == current_password:
            error = 'Choose a password different from the current one.'
        else:
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('profile.my_profile'))
    return render_template('pages/change_password.html', error=error,
                           forced=current_user.must_change_password), 400 if error else 200
