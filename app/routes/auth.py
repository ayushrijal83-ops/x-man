from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models import Authority

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not username or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('auth.register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('auth.register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('auth.register'))
        
        user = User(username=username, email=email, role='citizen')
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Citizen login."""
    if current_user.is_authenticated:
        if current_user.role == 'authority':
            return redirect(url_for('authority_panel.dashboard'))
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            
            # Redirect based on role
            if user.role == 'authority':
                return redirect(next_page or url_for('authority_panel.dashboard'))
            elif user.role == 'admin':
                return redirect(next_page or url_for('main.dashboard'))
            else:
                return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('auth/login.html')

@auth_bp.route('/authority/login', methods=['GET', 'POST'])
def authority_login():
    """Authority login."""
    if current_user.is_authenticated:
        if current_user.role == 'authority':
            return redirect(url_for('authority_panel.dashboard'))
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if user.role == 'authority' or user.role == 'admin':
                login_user(user, remember=remember)
                flash('Welcome to Authority Panel!', 'success')
                return redirect(url_for('authority_panel.dashboard'))
            else:
                flash('This account is not an authority account.', 'error')
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('auth/authority_login.html')

@auth_bp.route('/authority/register', methods=['GET', 'POST'])
def authority_register():
    """Authority registration."""
    if current_user.is_authenticated:
        return redirect(url_for('authority_panel.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        authority_name = request.form.get('authority_name')
        authority_category = request.form.get('authority_category')
        district_id = request.form.get('district_id')
        phone = request.form.get('phone')
        
        if not username or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('auth.authority_register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('auth.authority_register'))
        
        # Create authority record
        authority = Authority(
            name=authority_name,
            category=authority_category,
            district_id=int(district_id),
            phone=phone,
            is_verified=True
        )
        db.session.add(authority)
        db.session.flush()
        
        # Create user with authority role
        user = User(
            username=username,
            email=email,
            role='authority',
            district_id=int(district_id),
            is_verified=True
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Authority account created! Please login.', 'success')
        return redirect(url_for('auth.authority_login'))
    
    from app.models import District
    districts = District.query.order_by(District.name).all()
    return render_template('auth/authority_register.html', districts=districts)

@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))