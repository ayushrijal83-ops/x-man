from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Post, Comment, Like, District
from app.services.ai_service import AIService
import os
import uuid
from werkzeug.utils import secure_filename

post_bp = Blueprint('posts', __name__)
ai_service = AIService()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@post_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    """Create a new post with AI classification and photo upload."""
    if request.method == 'POST':
        content = request.form.get('content')
        district_id = request.form.get('district_id', current_user.district_id)
        category = request.form.get('category', 'general')
        location = request.form.get('location', '')
        
        if not content:
            flash('Post content is required.', 'error')
            return redirect(url_for('posts.create_post'))
        
        # Handle photo upload
        photo_path = None
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename and allowed_file(photo.filename):
                # Generate unique filename
                ext = photo.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                
                # Ensure upload directory exists
                upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                
                # Save file
                photo_path = os.path.join('uploads', filename)
                photo.save(os.path.join(upload_dir, filename))
        
        # AI Classification
        ai_result = ai_service.classify_post(content)
        
        post = Post(
            user_id=current_user.id,
            district_id=district_id,
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