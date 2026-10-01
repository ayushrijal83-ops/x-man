from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Post, Comment, Like, District
from app.services.ai_service import AIService
import os
import uuid

from app.services.citizen_report_service import ReportError, process_image
from app.services.form_validation import int_in_range

post_bp = Blueprint('posts', __name__)
ai_service = AIService()

MAX_CONTENT = 5000

@post_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    """Create a new post with AI classification and photo upload."""
    if request.method == 'POST':
        content = (request.form.get('content') or '').strip()
        district = db.session.get(District, int_in_range(
            request.form.get('district_id', current_user.district_id), 1, 2**31) or 0)
        category = request.form.get('category', 'general')
        location = (request.form.get('location') or '').strip()[:200]

        if not content or len(content) > MAX_CONTENT:
            flash('Post content is required.', 'error')
            return redirect(url_for('posts.create_post'))
        if district is None:  # was stored unchecked: orphan rows, or a 500 for users with no district
            flash('Choose a valid district.', 'error')
            return redirect(url_for('posts.create_post'))

        # Photos are public (static/uploads), so they go through the same pipeline as citizen
        # reports: decoded, type-checked, re-encoded as JPEG. That drops EXIF, including the GPS
        # position phones embed; the original bytes used to be served as-is.
        photo_path = None
        photo = request.files.get('photo')
        if photo is not None and photo.filename:
            try:
                jpeg = process_image(photo)
            except ReportError as e:
                flash(str(e), 'error')
                return redirect(url_for('posts.create_post'))
            filename = f"{uuid.uuid4().hex}.jpg"
            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            with open(os.path.join(upload_dir, filename), 'xb') as f:
                f.write(jpeg)
            photo_path = f'uploads/{filename}'

        # AI Classification
        ai_result = ai_service.classify_post(content)

        post = Post(
            user_id=current_user.id,
            district_id=district.id,
            content=content,
            category=ai_result.get('category', category),
            location=location,
            severity=ai_result.get('severity', 'low'),
            language=ai_result.get('language', 'ne'),
            is_ai_classified=True,
            photo_path=photo_path
        )

        db.session.add(post)
        db.session.commit()

        # Update user reputation
        current_user.reputation = (current_user.reputation or 0) + 5
        db.session.commit()

        flash(f'Post created! AI detected: {post.category} ({post.severity})', 'success')
        return redirect(url_for('main.dashboard'))

    districts = District.query.order_by(District.name).all()
    return render_template('pages/create_post.html', districts=districts)