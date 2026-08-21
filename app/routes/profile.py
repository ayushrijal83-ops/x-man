from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Post, Complaint, District, Like, Comment
from werkzeug.security import generate_password_hash

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
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        district_id = request.form.get('district_id')
        bio = request.form.get('bio')
        phone = request.form.get('phone')
        
        # Validate username
        if username and username != current_user.username:
            existing = User.query.filter_by(username=username).first()
            if existing:
                flash('Username already taken.', 'error')
                return redirect(url_for('profile.edit_profile'))
            current_user.username = username
        
        # Validate email
        if email and email != current_user.email:
            existing = User.query.filter_by(email=email).first()
            if existing:
                flash('Email already registered.', 'error')
                return redirect(url_for('profile.edit_profile'))
            current_user.email = email
        
        if district_id:
            current_user.district_id = int(district_id)
        
        # Store additional info in a simple way (could add columns to User model)
        current_user.bio = bio if bio else None
        current_user.phone = phone if phone else None
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile.my_profile'))
    
    districts = District.query.order_by(District.name).all()
    return render_template('pages/edit_profile.html', districts=districts)

@profile_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password."""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('profile.change_password'))
        
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('profile.change_password'))
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('profile.change_password'))
        
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        flash('Password changed successfully!', 'success')
        return redirect(url_for('profile.my_profile'))
    
    return render_template('pages/change_password.html')