from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Post, Comment, Like, District, User
from app.services.ai_service import AIService

social_bp = Blueprint('social', __name__)
ai_service = AIService()

@social_bp.route('/feed')
@login_required
def feed():
    """Main social feed."""
    # Get filter parameters
    district_id = request.args.get('district_id')
    category = request.args.get('category')
    hashtag = request.args.get('hashtag')
    
    # Build query
    query = Post.query

    scope_id = None
    if district_id == 'all':
        scope_id = None                      # explicit "show every district"
    elif district_id:
        scope_id = int(district_id)
    elif current_user.district_id:
        scope_id = current_user.district_id
    if scope_id:
        query = query.filter_by(district_id=scope_id)

    if category:
        query = query.filter_by(category=category)

    # Get posts
    posts = query.order_by(Post.created_at.desc()).limit(50).all()

    # Get districts for filter
    districts = District.query.order_by(District.name).all()

    # Trending must use the same scope as the feed. Counting nationwide while
    # the feed was filtered to one district showed "No posts found" next to
    # trending topics claiming three posts existed.
    trending_q = db.session.query(Post.category, db.func.count(Post.id))
    if scope_id:
        trending_q = trending_q.filter(Post.district_id == scope_id)
    trending = (trending_q.group_by(Post.category)
                .order_by(db.func.count(Post.id).desc()).limit(5).all())

    scope_district = District.query.get(scope_id) if scope_id else None

    # Get all users for display
    users = {u.id: u for u in User.query.all()}
    
    return render_template('pages/social_feed.html',
                         posts=posts,
                         districts=districts,
                         trending=trending,
                         users=users,
                         selected_district=district_id,
                         selected_category=category,
                         scope_district=scope_district)

@social_bp.route('/post/<int:post_id>')
@login_required
def post_detail(post_id):
    """View single post with comments."""
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at).all()
    likes_count = Like.query.filter_by(post_id=post_id).count()
    user = User.query.get(post.user_id)
    
    return render_template('pages/social_post_detail.html',
                         post=post,
                         comments=comments,
                         likes_count=likes_count,
                         user=user)

@social_bp.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def like_post(post_id):
    """Like/unlike a post."""
    existing_like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        return {'status': 'unliked'}
    else:
        like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(like)
        db.session.commit()
        return {'status': 'liked'}

@social_bp.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def comment_post(post_id):
    """Add comment to post."""
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
    
    return redirect(url_for('social.post_detail', post_id=post_id))

@social_bp.route('/hashtag/<hashtag>')
@login_required
def hashtag_feed(hashtag):
    """View posts by hashtag."""
    posts = Post.query.filter(Post.content.contains(hashtag)).order_by(Post.created_at.desc()).all()
    return render_template('pages/social_feed.html',
                         posts=posts,
                         districts=District.query.all(),
                         trending=[],
                         users={u.id: u for u in User.query.all()},
                         selected_district=None,
                         selected_category=None,
                         active_hashtag=hashtag)