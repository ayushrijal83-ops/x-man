"""Multi-signal risk evaluation (M08).

    evidence (telemetry / reports / AI / authority)
      -> gather from the DB here (district/river scoped)
      -> risk_engine rules (pure, explainable)          -> RiskAssessment
      -> hazard_event_service (create / merge, M02/M04)  -> Incident
      -> notification_service (only via hazard_event_service, M03/M04)

This module never creates notifications and never sets status. Inputs are server-side
evidence only; no client value (severity, risk level, confidence) is read here.
"""
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import IoTDevice
from app.models.iot_device import SensorReading
from app.services import risk_engine
from app.services.hazard_event_service import auto_create_flood_event_from_river, report_hazard

FLOOD_WINDOW = timedelta(minutes=30)
MOTION_WINDOW = timedelta(seconds=60)
MOTION_EVENT_TITLE = 'Abnormal ground motion signal: {}'
MOTION_DISCLAIMER = ('Prototype motion sensor evidence. Not a certified earthquake detection, '
                     'not a prediction and no magnitude.')


def _readings(device_ids, sensor_types, since):
    if not device_ids:
        return []
    return SensorReading.query.filter(
        SensorReading.device_id.in_(device_ids),
        SensorReading.sensor_type.in_(sensor_types),
        SensorReading.received_at >= since,
    ).all()


def _river_device_ids(river, extra_device=None):
    ids = [i for (i,) in db.session.query(IoTDevice.id).filter(IoTDevice.river_id == river.id)]
    if extra_device is not None and extra_device.id not in ids:
        ids.append(extra_device.id)  # M01 fallback: device mapped to its district's river
    return ids


def flood_assessment(river, current_level, device=None, now=None):
    since = (now or datetime.utcnow()) - FLOOD_WINDOW
    readings = [r for r in _readings(_river_device_ids(river, device), ['water_level'], since) if r.unit == 'm']
    return risk_engine.assess_flood(current_level, river.danger_level, readings, district_id=river.district_id)


def evaluate_water_level(device, river, water_level):
    """Called by telemetry ingestion for each valid water_level reading (metres)."""
    assessment = flood_assessment(river, water_level, device)
    if assessment.action_warranted:
        # M02 owns create/merge/escalation and hands state changes to M03/M04 notifications
        auto_create_flood_event_from_river(river, {
            'status': assessment.level,
            'risk_level': assessment.evidence['risk_level'],
            'alert_required': True,
            'percentage': assessment.evidence['percentage'],
            'reason': assessment.reasons[0],
        }, device)
    return assessment


def motion_assessment(device, now=None):
    since = (now or datetime.utcnow()) - MOTION_WINDOW
    readings = _readings([device.id], ['vibration', 'tilt'], since)
    config = current_app.config
    return risk_engine.assess_motion(
        [r for r in readings if r.sensor_type == 'vibration'],
        [r for r in readings if r.sensor_type == 'tilt'],
        vibration_threshold_mg=config.get('MOTION_VIBRATION_THRESHOLD_MG'),
        tilt_change_deg=config.get('MOTION_TILT_CHANGE_THRESHOLD_DEG'),
        district_id=device.district_id,
    )


def evaluate_motion(device):
    """Called by telemetry ingestion after vibration/tilt readings from `device` were stored."""
    assessment = motion_assessment(device)
    if assessment.action_warranted and device.district_id:
        has_coords = device.latitude is not None and device.longitude is not None
        # escalate=False: repeated motion evidence merges into the active event (M02 dedup)
        # without raising its severity; escalation stays an authority decision
        report_hazard(
            'earthquake', assessment.severity, 'iot', escalate=False,
            district_id=device.district_id,
            latitude=device.latitude if has_coords else None,
            longitude=device.longitude if has_coords else None,
            location=device.location_description,
            title=MOTION_EVENT_TITLE.format(device.name),
            description=f'{assessment.reasons[0]}. {MOTION_DISCLAIMER}',
            source_reference=f'device_{device.id}',
        )
    return assessment


def assess_incident(incident):
    """Read-only multi-signal view of the evidence behind one event. Uses only evidence linked to
    it (its river, devices in its primary district, reports attached to it), never other districts."""
    authority = incident.source == 'authority'
    if incident.event_type == 'flood':
        river = incident.river
        if river is None:
            return [risk_engine.RiskAssessment('flood', 'unknown', reasons=['Event has no linked river'],
                                               sources=['authority'] if authority else [],
                                               district_id=incident.district_id)]
        return [flood_assessment(river, river.current_level)]
    if incident.event_type == 'earthquake':
        devices = IoTDevice.query.filter(IoTDevice.district_id == incident.district_id).order_by(IoTDevice.id).all() \
            if incident.district_id else []
        results = []
        for device in devices:
            assessment = motion_assessment(device)
            assessment.evidence['device'] = device.name
            results.append(assessment)
        if not results:
            results.append(risk_engine.RiskAssessment(
                'earthquake', 'insufficient', reasons=['No motion devices in the event district'],
                sources=['authority'] if authority else [], district_id=incident.district_id))
        return results
    return [risk_engine.assess_visual(incident.event_type, list(incident.citizen_reports),
                                      authority_source=authority, district_id=incident.district_id)]
