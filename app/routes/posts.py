from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Post, Comment, Like, District

post_bp = Blueprint('posts', __name__)

@post_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    """Create a new post."""
    if request.method == 'POST':
        content = request.form.get('content')
        district_id = request.form.get('district_id', current_user.district_id)
        category = request.form.get('category', 'general')
        location = request.form.get('location')
        
        if not content:
            flash('Post content is required.', 'error')
            return redirect(request.referrer or url_for('main.dashboard'))
        
        post = Post(
            user_id=current_user.id,
            district_id=district_id,
            content=content,
            category=category,
            location=location
        )
        
        db.session.add(post)
        db.session.commit()
        
        flash('Post created successfully!', 'success')
        return redirect(url_for('main.dashboard'))
    
    districts = District.query.order_by(District.name).all()
    return render_template('pages/create_post.html', districts=districts)

@post_bp.route('/<int:post_id>')
@login_required
def post_detail(post_id):
    """View a single post."""
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at).all()
    return render_template('pages/post_detail.html', post=post, comments=comments)

@post_bp.route('/<int:post_id>/like', methods=['POST'])
@login_required
def like_post(post_id):
    """Like a post."""
    existing_like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        return jsonify({'status': 'unliked'})
    else:
        like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(like)
        db.session.commit()
        return jsonify({'status': 'liked'})

@post_bp.route('/<int:post_id>/comment', methods=['POST'])
@login_required
def comment_post(post_id):
    """Comment on a post."""
    content = request.form.get('content')
    
    if content:
        comment = Comment(
            user_id=current_user.id,
            post_id=post_id,
            content=content
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comment added!', 'success')
    
    return redirect(url_for('posts.post_detail', post_id=post_id))