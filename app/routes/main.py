from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user, login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('pages/landing.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('pages/dashboard.html')