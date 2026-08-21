from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.models import RoadSegment, Incident, River

travel_bp = Blueprint('travel', __name__)

@travel_bp.route('/planner', methods=['GET', 'POST'])
@login_required
def travel_planner():
    """Travel planning page."""
    if request.method == 'POST':
        from_location = request.form.get('from_location')
        to_location = request.form.get('to_location')
        travel_date = request.form.get('travel_date')
        travel_time = request.form.get('travel_time')
        
        if not from_location or not to_location:
            flash('Please enter both locations.', 'error')
            return redirect(url_for('travel.travel_planner'))
        
        roads = RoadSegment.query.all()
        incidents = Incident.query.filter_by(status='active').all()
        rivers = River.query.filter(River.status.in_(['high', 'flooding'])).all()
        
        risk_score = 0
        warnings = []
        
        for road in roads:
            if road.status == 'blocked':
                risk_score += 50
                warnings.append(f"Road BLOCKED: {road.name}")
            elif road.status == 'partial':
                risk_score += 25
                warnings.append(f"Road PARTIALLY OPEN: {road.name}")
        
        for incident in incidents:
            if incident.severity == 'critical':
                risk_score += 40
                warnings.append(f"CRITICAL: {incident.category}")
            elif incident.severity == 'high':
                risk_score += 20
                warnings.append(f"HIGH: {incident.category}")
        
        for river in rivers:
            risk_score += 30
            warnings.append(f"River {river.status.upper()}: {river.name}")
        
        if risk_score >= 100:
            travel_score = 1
            recommendation = "Travel NOT RECOMMENDED"
            explanation = "Multiple critical issues detected."
        elif risk_score >= 70:
            travel_score = 2
            recommendation = "Travel with EXTREME CAUTION"
            explanation = "Several significant issues detected."
        elif risk_score >= 40:
            travel_score = 3
            recommendation = "Travel with CAUTION"
            explanation = "Some issues detected. Allow extra time."
        elif risk_score >= 15:
            travel_score = 4
            recommendation = "Travel conditions GENERALLY GOOD"
            explanation = "Minor issues detected."
        else:
            travel_score = 5
            recommendation = "Travel conditions EXCELLENT"
            explanation = "No significant issues detected."
        
        total_distance = sum(r.distance_km or 0 for r in roads)
        avg_speed = 40 if travel_score >= 4 else 30 if travel_score >= 3 else 20
        estimated_hours = total_distance / avg_speed if total_distance > 0 else 0
        
        return render_template('pages/travel_result.html',
                             from_location=from_location,
                             to_location=to_location,
                             travel_date=travel_date,
                             travel_time=travel_time,
                             risk_score=risk_score,
                             travel_score=travel_score,
                             recommendation=recommendation,
                             explanation=explanation,
                             warnings=warnings,
                             roads=roads,
                             incidents=incidents,
                             rivers=rivers,
                             estimated_hours=round(estimated_hours, 1),
                             total_distance=total_distance)
    
    return render_template('pages/travel_planner.html')