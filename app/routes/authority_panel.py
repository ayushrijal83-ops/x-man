from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Complaint, Authority, Project, RoadSegment, River, AuthorityResponse
from datetime import datetime

authority_panel_bp = Blueprint('authority_panel', __name__)

def get_authority():
    """Get authority associated with current user."""
    # For demo, find authority by name matching username
    authority = Authority.query.filter_by(name=current_user.username).first()
    if not authority:
        # Fallback: get first authority
        authority = Authority.query.first()
    return authority

@authority_panel_bp.route('/dashboard')
@login_required
def dashboard():
    """Authority dashboard."""
    authority = get_authority()
    
    if not authority:
        flash('No authority found for your account.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Get complaints for this authority
    complaints = Complaint.query.filter_by(authority_id=authority.id).order_by(Complaint.created_at.desc()).all()
    
    # Get projects
    projects = Project.query.filter_by(authority_id=authority.id).all()
    
    # Get roads in district
    roads = RoadSegment.query.filter_by(district_id=authority.district_id).all()
    
    # Get rivers in district
    rivers = River.query.filter_by(district_id=authority.district_id).all()
    
    # Stats
    total_complaints = len(complaints)
    pending = len([c for c in complaints if c.status == 'pending'])
    in_progress = len([c for c in complaints if c.status == 'in_progress'])
    resolved = len([c for c in complaints if c.status == 'resolved'])
    
    return render_template('authority/dashboard.html',
                         authority=authority,
                         complaints=complaints[:10],
                         projects=projects,
                         roads=roads,
                         rivers=rivers,
                         total_complaints=total_complaints,
                         pending=pending,
                         in_progress=in_progress,
                         resolved=resolved)

@authority_panel_bp.route('/complaints')
@login_required
def complaints():
    """View all complaints for authority."""
    authority = get_authority()
    complaints = Complaint.query.filter_by(authority_id=authority.id).order_by(Complaint.created_at.desc()).all()
    return render_template('authority/complaints.html', 
                         authority=authority,
                         complaints=complaints)

@authority_panel_bp.route('/complaints/<int:complaint_id>', methods=['GET', 'POST'])
@login_required
def complaint_detail(complaint_id):
    """View and respond to complaint."""
    complaint = Complaint.query.get_or_404(complaint_id)
    authority = get_authority()
    
    if request.method == 'POST':
        response_text = request.form.get('response')
        status_update = request.form.get('status')
        
        if response_text:
            response = AuthorityResponse(
                complaint_id=complaint_id,
                authority_id=authority.id,
                message=response_text,
                status_update=status_update
            )
            db.session.add(response)
        
        complaint.status = status_update
        complaint.government_response = response_text
        complaint.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash('Response sent successfully!', 'success')
        return redirect(url_for('authority_panel.complaints'))
    
    responses = AuthorityResponse.query.filter_by(complaint_id=complaint_id).all()
    return render_template('authority/complaint_detail.html',
                         complaint=complaint,
                         responses=responses)

@authority_panel_bp.route('/projects')
@login_required
def projects():
    """View authority projects."""
    authority = get_authority()
    projects = Project.query.filter_by(authority_id=authority.id).all()
    return render_template('authority/projects.html',
                         authority=authority,
                         projects=projects)

@authority_panel_bp.route('/projects/<int:project_id>/update', methods=['POST'])
@login_required
def update_project(project_id):
    """Update project progress."""
    project = Project.query.get_or_404(project_id)
    
    progress = request.form.get('progress_percent')
    description = request.form.get('description')
    
    if progress:
        project.progress_percent = int(progress)
        if int(progress) >= 100:
            project.status = 'completed'
        elif int(progress) >= 50:
            project.status = 'on_schedule'
        else:
            project.status = 'delayed'
    
    if description:
        from app.models import ProjectUpdate
        update = ProjectUpdate(
            project_id=project_id,
            authority_id=project.authority_id,
            update_type='progress',
            description=description,
            progress_percent=int(progress) if progress else None
        )
        db.session.add(update)
    
    db.session.commit()
    flash('Project updated!', 'success')
    return redirect(url_for('authority_panel.projects'))

@authority_panel_bp.route('/roads')
@login_required
def roads():
    """View and update roads."""
    authority = get_authority()
    roads = RoadSegment.query.filter_by(district_id=authority.district_id).all()
    return render_template('authority/roads.html',
                         authority=authority,
                         roads=roads)

@authority_panel_bp.route('/roads/<int:road_id>/update', methods=['POST'])
@login_required
def update_road(road_id):
    """Update road status."""
    road = RoadSegment.query.get_or_404(road_id)
    
    status = request.form.get('status')
    traffic = request.form.get('traffic_level')
    description = request.form.get('description')
    
    road.status = status
    road.traffic_level = traffic
    road.last_updated = datetime.utcnow()
    
    if description:
        from app.models import RoadUpdate
        update = RoadUpdate(
            road_segment_id=road_id,
            user_id=current_user.id,
            update_type='authority_update',
            description=description,
            status=status
        )
        db.session.add(update)
    
    db.session.commit()
    flash('Road status updated!', 'success')
    return redirect(url_for('authority_panel.roads'))

@authority_panel_bp.route('/rivers')
@login_required
def rivers():
    """View and update rivers."""
    authority = get_authority()
    rivers = River.query.filter_by(district_id=authority.district_id).all()
    return render_template('authority/rivers.html',
                         authority=authority,
                         rivers=rivers)

@authority_panel_bp.route('/rivers/<int:river_id>/update', methods=['POST'])
@login_required
def update_river(river_id):
    """Update river status."""
    river = River.query.get_or_404(river_id)
    
    water_level = request.form.get('water_level')
    status = request.form.get('status')
    
    if water_level:
        river.current_level = float(water_level)
    
    if status:
        river.status = status
    
    river.last_updated = datetime.utcnow()
    
    db.session.commit()
    flash('River status updated!', 'success')
    return redirect(url_for('authority_panel.rivers'))