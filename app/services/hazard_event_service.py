"""Hazard Event Service (M02).

Business logic for the hazard-event layer. Every source (IoT, citizen report,
authority, system) goes through here and produces/updates an Incident.
Notification delivery is NOT done here (M03).
"""

import math
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Incident, River, RoadSegment, District
from app.models.incident import (
    HAZARD_TYPES, HAZARD_SOURCES, HAZARD_SEVERITY, HAZARD_STATUS,
    ACTIVE_STATUSES, VALID_STATUS_TRANSITIONS,
)

# An active event with evidence newer than this is "the same hazard" for
# district/location matches. River/road matches ignore the window.
DEDUP_WINDOW_HOURS = 24
DEDUP_DISTANCE_KM = 5.0

# risk_engine risk_level (0 unknown, 1 normal, 2 rising, 3 flooding) -> severity
RISK_LEVEL_SEVERITY = {2: 'medium', 3: 'high'}


def _validate_hazard_type(event_type):
    if event_type not in HAZARD_TYPES:
        raise ValueError(f"Invalid hazard type: {event_type}. Must be one of {HAZARD_TYPES}")


def _validate_severity(severity):
    if severity not in HAZARD_SEVERITY:
        raise ValueError(f"Invalid severity: {severity}. Must be one of {HAZARD_SEVERITY}")


def _validate_source(source):
    if source not in HAZARD_SOURCES:
        raise ValueError(f"Invalid source: {source}. Must be one of {HAZARD_SOURCES}")


def _validate_status(status):
    if status not in HAZARD_STATUS:
        raise ValueError(f"Invalid status: {status}. Must be one of {HAZARD_STATUS}")


def _validate_coordinates(latitude, longitude):
    if (latitude is None) != (longitude is None):
        raise ValueError("Latitude and longitude must be provided together")
    if latitude is None:
        return
    for name, value in (('Latitude', latitude), ('Longitude', longitude)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a number")
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180")


def _validate_confidence(confidence):
    if confidence is None:
        return
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        raise ValueError("Confidence must be a number between 0.0 and 1.0")


def _bounding_box(latitude, longitude, radius_km):
    lat_delta = radius_km / 111.0
    # a degree of longitude shrinks with cos(latitude)
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(latitude)), 0.01))
    return (Incident.latitude.between(latitude - lat_delta, latitude + lat_delta),
            Incident.longitude.between(longitude - lon_delta, longitude + lon_delta))


def create_hazard_event(event_type, severity, source, district_id=None, location=None,
                        latitude=None, longitude=None, river_id=None, road_segment_id=None,
                        title=None, description=None, source_reference=None,
                        confidence=None, detected_at=None):
    """Validate and create a new hazard event in 'detected' status. Raises ValueError."""
    _validate_hazard_type(event_type)
    _validate_severity(severity)
    _validate_source(source)
    _validate_coordinates(latitude, longitude)
    _validate_confidence(confidence)

    if district_id and not db.session.get(District, district_id):
        raise ValueError(f"Invalid district_id: {district_id}")
    river = db.session.get(River, river_id) if river_id else None
    if river_id and not river:
        raise ValueError(f"Invalid river_id: {river_id}")
    road = db.session.get(RoadSegment, road_segment_id) if road_segment_id else None
    if road_segment_id and not road:
        raise ValueError(f"Invalid road_segment_id: {road_segment_id}")
    for linked in (river, road):
        if linked and district_id and linked.district_id and linked.district_id != district_id:
            raise ValueError("River/road segment does not belong to the given district")

    now = datetime.utcnow()
    incident = Incident(
        event_type=event_type,
        severity=severity,
        source=source,
        district_id=district_id,
        location=location,
        latitude=latitude,
        longitude=longitude,
        river_id=river_id,
        road_segment_id=road_segment_id,
        title=title,
        description=description,
        source_reference=source_reference,
        status='detected',
        confidence=confidence,
        report_count=1,
        detected_at=detected_at or now,
        updated_at=now,
    )
    db.session.add(incident)
    db.session.commit()
    return incident


def find_active_related_event(event_type, district_id=None, river_id=None, road_segment_id=None,
                              latitude=None, longitude=None, hours=None):
    """Return the active event that new evidence belongs to, or None.

    - same river / road segment: one active event per (type, river|road), no time window
    - otherwise: same district and/or within DEDUP_DISTANCE_KM, with evidence in the last `hours`
    """
    query = Incident.query.filter(
        Incident.event_type == event_type,
        Incident.status.in_(ACTIVE_STATUSES),
    )

    if river_id:
        query = query.filter(Incident.river_id == river_id)
    elif road_segment_id:
        query = query.filter(Incident.road_segment_id == road_segment_id)
    else:
        if district_id is None and latitude is None:
            return None  # nothing to match on
        since = datetime.utcnow() - timedelta(hours=hours or DEDUP_WINDOW_HOURS)
        query = query.filter(db.func.coalesce(Incident.updated_at, Incident.detected_at) >= since)
        if district_id:
            query = query.filter(Incident.district_id == district_id)
        if latitude is not None and longitude is not None:
            query = query.filter(*_bounding_box(latitude, longitude, DEDUP_DISTANCE_KM))

    return query.order_by(Incident.detected_at.desc()).first()


def add_evidence(incident, severity=None, source_reference=None):
    """Attach a new piece of evidence to an existing active event.

    Bumps report_count and escalates severity (never lowers it automatically;
    lowering is an authority decision). Does not change lifecycle status.
    """
    incident.report_count = (incident.report_count or 0) + 1
    if severity and HAZARD_SEVERITY.index(severity) > HAZARD_SEVERITY.index(incident.severity or 'low'):
        incident.severity = severity
    if source_reference:
        incident.source_reference = source_reference
    incident.updated_at = datetime.utcnow()
    db.session.commit()
    return incident


def report_hazard(event_type, severity, source, **fields):
    """Create a new event, or merge into the matching active one. Returns (incident, created)."""
    _validate_hazard_type(event_type)
    _validate_severity(severity)
    _validate_coordinates(fields.get('latitude'), fields.get('longitude'))
    existing = find_active_related_event(
        event_type,
        district_id=fields.get('district_id'),
        river_id=fields.get('river_id'),
        road_segment_id=fields.get('road_segment_id'),
        latitude=fields.get('latitude'),
        longitude=fields.get('longitude'),
    )
    if existing:
        return add_evidence(existing, severity, fields.get('source_reference')), False
    return create_hazard_event(event_type, severity, source, **fields), True


def transition_event_status(incident, new_status):
    """Validated lifecycle transition. Returns old status. Raises ValueError."""
    _validate_status(new_status)
    old_status = incident.transition_status(new_status)
    db.session.commit()
    return old_status


def _transition_with_note(incident, new_status, label, note):
    old_status = incident.transition_status(new_status)
    if note:
        incident.description = (incident.description or '') + f'\n\n{label}: {note}'
    db.session.commit()
    return old_status


def resolve_event(incident, resolution_notes=None):
    _transition_with_note(incident, 'resolved', 'Resolution', resolution_notes)
    return incident


def reject_event(incident, reason=None):
    _transition_with_note(incident, 'rejected', 'Rejection reason', reason)
    return incident


def escalate_to_investigating(incident):
    transition_event_status(incident, 'investigating')
    return incident


def confirm_event(incident):
    transition_event_status(incident, 'confirmed')
    return incident


def update_event_from_iot(incident, risk_assessment, source_reference=None):
    """Apply a repeated rising/flooding reading to an existing flood event."""
    if incident.event_type != 'flood':
        return False
    add_evidence(incident, RISK_LEVEL_SEVERITY.get(risk_assessment['risk_level']), source_reference)
    return True


def auto_create_flood_event_from_river(river, risk_assessment, device=None):
    """Bridge from the deterministic M01 risk engine to the event layer.

    Only rising/flooding assessments produce evidence; normal/unknown returns None.
    risk_engine stays authoritative for the threshold decision.
    """
    if risk_assessment['status'] not in ('rising', 'flooding') or not risk_assessment.get('alert_required', True):
        return None

    source_ref = f'device_{device.id}' if device else f'river_{river.id}'
    existing = find_active_related_event('flood', river_id=river.id)
    if existing:
        update_event_from_iot(existing, risk_assessment, source_ref)
        return existing

    district = db.session.get(District, river.district_id) if river.district_id else None
    district_name = district.name if district else None
    percentage = risk_assessment.get('percentage')
    has_coords = device is not None and device.latitude is not None and device.longitude is not None

    return create_hazard_event(
        event_type='flood',
        severity=RISK_LEVEL_SEVERITY[risk_assessment['risk_level']],
        source='iot',
        district_id=river.district_id,
        location=district_name,
        latitude=device.latitude if has_coords else None,
        longitude=device.longitude if has_coords else None,
        river_id=river.id,
        title=f"{risk_assessment['status'].title()} detected: {river.name}",
        description=(
            f"{river.name} in {district_name or 'unknown district'} is {risk_assessment['status']} "
            f"at {river.current_level}m"
            + (f" ({percentage:.0f}% of danger level)" if percentage is not None else "")
            + f". {risk_assessment.get('reason', '')}"
        ).strip(),
        source_reference=source_ref,
        confidence=None,  # deterministic threshold, not a probabilistic model
    )


def get_active_events_for_district(district_id):
    return Incident.query.filter(
        Incident.district_id == district_id,
        Incident.status.in_(ACTIVE_STATUSES),
    ).order_by(Incident.detected_at.desc()).all()


def get_events_by_type(event_type, status=None, limit=100):
    query = Incident.query.filter_by(event_type=event_type)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Incident.detected_at.desc()).limit(limit).all()


def get_events_by_source(source, limit=100):
    return Incident.query.filter_by(source=source).order_by(Incident.detected_at.desc()).limit(limit).all()


def get_events_near_location(latitude, longitude, radius_km=10, limit=50):
    return Incident.query.filter(*_bounding_box(latitude, longitude, radius_km)) \
        .order_by(Incident.detected_at.desc()).limit(limit).all()


def get_event_statistics():
    def counts(column, keys):
        rows = dict(db.session.query(column, db.func.count(Incident.id)).group_by(column).all())
        return {k: rows.get(k, 0) for k in keys}

    return {
        'total': Incident.query.count(),
        'by_status': counts(Incident.status, HAZARD_STATUS),
        'by_type': counts(Incident.event_type, HAZARD_TYPES),
        'by_source': counts(Incident.source, HAZARD_SOURCES),
        'by_severity': counts(Incident.severity, HAZARD_SEVERITY),
    }
