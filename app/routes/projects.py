from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Project, ProjectUpdate, District
from datetime import datetime

projects_bp = Blueprint('projects', __name__)

@projects_bp.route('/tracker')
@login_required
def project_tracker():
    """Show project tracker."""
    district_id = request.args.get('district_id')
    
    if district_id:
        projects = Project.query.filter_by(district_id=int(district_id)).all()
    else:
        projects = Project.query.all()
    
    districts = District.query.order_by(District.name).all()
    
    return render_template('pages/project_tracker.html',
                         projects=projects,
                         districts=districts,
                         selected_district=district_id)

@projects_bp.route('/<int:project_id>')
@login_required
def project_detail(project_id):
    """View project details."""
    project = Project.query.get_or_404(project_id)
    updates = ProjectUpdate.query.filter_by(project_id=project_id).order_by(ProjectUpdate.created_at.desc()).all()
    return render_template('pages/project_detail.html', project=project, updates=updates)

@projects_bp.route('/<int:project_id>/update', methods=['POST'])
@login_required
def update_project(project_id):
    """Update project progress."""
    project = Project.query.get_or_404(project_id)
    
    progress = request.form.get('progress_percent')
    description = request.form.get('description')
    update_type = request.form.get('update_type', 'progress')
    
    if progress:
        progress = int(progress)
        project.progress_percent = progress
        
        if progress >= 100:
            project.status = 'completed'
        elif progress < 30:
            project.status = 'delayed'
        else:
            project.status = 'on_schedule'
    
    update = ProjectUpdate(
        project_id=project_id,
        authority_id=project.authority_id,
        update_type=update_type,
        description=description,
        progress_percent=progress if progress else None
    )
    
    db.session.add(update)
    db.session.commit()
    
    flash('Project updated successfully!', 'success')
    return redirect(url_for('projects.project_detail', project_id=project_id))