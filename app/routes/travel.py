from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required
from app.models import RoadSegment, Incident, River, District

travel_bp = Blueprint('travel', __name__)

# Rivers at or near their danger mark. 'rising' was missing here, so a river
# at 80% of its danger level counted as no risk at all.
RISKY_RIVER_STATUS = ['rising', 'flooding', 'high']


def _districts_for(*places):
    """Districts whose name appears in any of the given place strings."""
    found = []
    for d in District.query.all():
        low = d.name.lower()
        for place in places:
            if place and (low in place.lower() or place.lower() in low):
                found.append(d)
                break
    return found


def _roads_on_route(from_location, to_location):
    """Roads plausibly on the route, plus whether we actually narrowed it down.

    ponytail: name/district matching, not real routing -- there is no graph of
    the network here. Good enough to stop the planner summing every road in
    Nepal; swap for a real path search if routing quality starts to matter.
    """
    districts = _districts_for(from_location, to_location)
    q = RoadSegment.query
    clauses = []
    if districts:
        clauses.append(RoadSegment.district_id.in_([d.id for d in districts]))
    for place in (from_location, to_location):
        if place:
            like = '%%%s%%' % place.strip()
            clauses.append(RoadSegment.from_location.ilike(like))
            clauses.append(RoadSegment.to_location.ilike(like))
    if clauses:
        from sqlalchemy import or_
        roads = q.filter(or_(*clauses)).all()
        if roads:
            return roads, True
    return q.all(), False

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
        
        roads, route_matched = _roads_on_route(from_location, to_location)
        district_ids = [r.district_id for r in roads]
        incidents = Incident.query.filter_by(status='active').all()
        rivers = (River.query
                  .filter(River.status.in_(RISKY_RIVER_STATUS))
                  .filter(River.district_id.in_(district_ids) if district_ids else True)
                  .all())

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

        # the same segment can match on both district and place name
        warnings = list(dict.fromkeys(warnings))
        # score is presented out of 100, so don't let it run past that
        risk_score = min(risk_score, 100)

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
        
        # de-duplicate segments before summing -- the same road can be matched twice
        total_distance = sum(r.distance_km or 0 for r in {rd.id: rd for rd in roads}.values())
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
                             total_distance=total_distance,
                             route_matched=route_matched)
    
    return render_template('pages/travel_planner.html')