from flask import Blueprint, current_app, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.user import User
from app.models import Authority, District
from app.services import account_service

auth_bp = Blueprint('auth', __name__)


def _safe_next(target):
    """Only same-site relative paths for ?next= (M10: blocks open redirects such as
    //evil.example, https://evil.example or /\\evil.example)."""
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return None
    return target

DISABLED_MESSAGE = 'This account has been disabled. Contact an administrator.'


def _login(user, remember):
    login_user(user, remember=remember)
    user.last_login_at = datetime.utcnow()  # M12: "last activity" in the admin directory
    db.session.commit()


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    districts = District.query.order_by(District.name).all()
    if request.method == 'POST':
        data, errors = account_service.validate_registration(request.form, User, District, db)
        if errors:
            # re-render with what the user typed (never the password) and per-field messages
            return render_template('auth/register.html', districts=districts, errors=errors,
                                   form=request.form), 400

        user = User(username=data['username'], email=data['email'], role='citizen',
                    full_name=data['full_name'], phone=data['mobile'], phone_verified=False,
                    permanent_address=data['permanent_address'], district_id=data['district_id'])
        account_service.set_current_location(user, data['current_latitude'], data['current_longitude'],
                                             data['current_address'] if data['current_latitude'] is not None
                                             else None)
        user.set_password(data['password'])
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:  # lost a race on username/email/mobile uniqueness
            db.session.rollback()
            return render_template('auth/register.html', districts=districts, form=request.form,
                                   errors={'form': 'That username, email or mobile number was just taken.'}), 400

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', districts=districts, errors={}, form={})

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
            if not user.is_active:  # only revealed to someone who knows the password
                return render_template('auth/login.html', error=DISABLED_MESSAGE, username=username), 403
            _login(user, remember)
            next_page = _safe_next(request.args.get('next'))
            if user.must_change_password:
                return redirect(url_for('profile.change_password'))

            # Redirect based on role
            if user.role == 'authority':
                return redirect(next_page or url_for('authority_panel.dashboard'))
            elif user.role == 'admin':
                return redirect(next_page or url_for('main.dashboard'))
            else:
                return redirect(next_page or url_for('main.dashboard'))
        # one message for unknown user and wrong password: no account enumeration
        return render_template('auth/login.html', error='Invalid username or password.',
                               username=username or ''), 401

    return render_template('auth/login.html', error=None, username='')

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
            if not user.is_active:
                flash(DISABLED_MESSAGE, 'error')
            elif user.role == 'authority' or user.role == 'admin':
                _login(user, remember)
                if user.must_change_password:
                    return redirect(url_for('profile.change_password'))
                flash('Welcome to Authority Panel!', 'success')
                return redirect(url_for('authority_panel.dashboard'))
            else:
                flash('This account is not an authority account.', 'error')
        else:
            flash('Invalid username or password.', 'error')

    return render_template('auth/authority_login.html')

@auth_bp.route('/authority/register', methods=['GET', 'POST'])
def authority_register():
    """Authority self-registration. Off unless AUTHORITY_SELF_REGISTRATION is enabled (M10):
    it creates a verified authority with manager rights over a district, so by default
    authority accounts are provisioned by an administrator."""
    if not current_app.config.get('AUTHORITY_SELF_REGISTRATION'):
        flash('Authority accounts are created by an administrator.', 'error')
        return redirect(url_for('auth.authority_login'))
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
            authority_id=authority.id,
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