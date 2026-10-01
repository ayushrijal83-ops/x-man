"""District overview and citizen home data (product-quality milestone).

Read-only and built from real rows. Totals are COUNT queries, never the length of a truncated
list. Only public information is returned: hazards use the public serializer (no
source_reference), and a citizen only ever sees their OWN reports and notifications.
"""
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import (Authority, CitizenReport, District, Incident, IncidentAffectedDistrict, Post, Project,
                        River, RoadSegment)
from app.models.incident import ACTIVE_STATUSES, HAZARD_SEVERITY
from app.services import notification_service
from app.services.hazard_event_service import affects_district

LIST_LIMIT = 12


def _status_counts(column, *filters):
    return dict(db.session.query(column, db.func.count()).filter(*filters).group_by(column).all())


def active_hazards_for(district_id, limit=50):
    return Incident.query.filter(affects_district(district_id), Incident.status.in_(ACTIVE_STATUSES)).options(
        joinedload(Incident.district),
        selectinload(Incident.additional_districts).joinedload(IncidentAffectedDistrict.district),
    ).order_by(Incident.updated_at.desc(), Incident.id.desc()).limit(limit).all()


def severity_summary(hazards):
    counts = dict.fromkeys(reversed(HAZARD_SEVERITY), 0)
    for h in hazards:
        counts[h.severity] = counts.get(h.severity, 0) + 1
    return counts


def highest_severity(hazards):
    levels = [HAZARD_SEVERITY.index(h.severity) for h in hazards if h.severity in HAZARD_SEVERITY]
    return HAZARD_SEVERITY[max(levels)] if levels else None


def mappable(hazards):
    """Only hazards with real coordinates; nothing is placed at an invented position."""
    return [{'id': h.id, 'type': h.event_type, 'severity': h.severity, 'status': h.status,
             'title': h.title or h.event_type, 'lat': h.latitude, 'lon': h.longitude}
            for h in hazards if h.latitude is not None and h.longitude is not None]


def district_overview(district):
    did = district.id
    hazards = active_hazards_for(did)
    rivers = River.query.filter_by(district_id=did).order_by(River.name).all()
    road_filter = RoadSegment.district_id == did
    return {
        'district': district,
        'hazards': hazards,
        'hazard_severity': severity_summary(hazards),
        'highest_severity': highest_severity(hazards),
        'map_points': mappable(hazards),
        'rivers': rivers,
        'river_status': _status_counts(River.status, River.district_id == did),
        'roads': RoadSegment.query.filter(road_filter).order_by(RoadSegment.name).limit(LIST_LIMIT).all(),
        'road_total': db.session.query(db.func.count(RoadSegment.id)).filter(road_filter).scalar(),
        'road_status': _status_counts(RoadSegment.status, road_filter),
        'projects': Project.query.filter_by(district_id=did).order_by(Project.name).all(),
        'authorities': Authority.query.filter_by(district_id=did).order_by(Authority.name).all(),
        'posts': Post.query.filter_by(district_id=did).order_by(Post.created_at.desc()).limit(6).all(),
        'post_total': db.session.query(db.func.count(Post.id)).filter(Post.district_id == did).scalar(),
    }


def citizen_home(user):
    """Everything on the citizen dashboard, scoped to the user's district and their own data."""
    district = db.session.get(District, user.district_id) if user.district_id else None
    overview = district_overview(district) if district else None
    my_reports = CitizenReport.query.filter_by(reporter_id=user.id)
    return {
        'district': district,
        'overview': overview,
        'nationwide_active': db.session.query(db.func.count(Incident.id))
        .filter(Incident.status.in_(ACTIVE_STATUSES)).scalar(),
        'alerts': notification_service.get_user_notifications(user.id, limit=6),
        'unread': notification_service.unread_count(user.id),
        'my_reports': my_reports.options(joinedload(CitizenReport.incident))
        .order_by(CitizenReport.created_at.desc()).limit(5).all(),
        'my_report_counts': _status_counts(CitizenReport.status, CitizenReport.reporter_id == user.id),
        'my_report_total': my_reports.count(),
    }


def public_stats():
    """Landing-page numbers, all counted (no hard-coded figures)."""
    from app.services.translation_service import TranslationService
    return {
        'districts': db.session.query(db.func.count(District.id)).scalar(),
        'provinces': db.session.query(db.func.count(db.distinct(District.province))).scalar(),
        'languages': len(TranslationService().get_supported_languages()),
        'active_hazards': db.session.query(db.func.count(Incident.id))
        .filter(Incident.status.in_(ACTIVE_STATUSES)).scalar(),
    }
