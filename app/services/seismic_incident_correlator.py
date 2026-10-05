"""Seismic Incident Correlator (Phase 4A).

Device Event (one abnormal-motion episode of one device) -> Incident (X-MAN hazard record).
Thin decision layer: decides CREATE_NEW or ATTACH_EXISTING on event_started and records the
association on the device's SeismicEventState. hazard_event_service owns Incident creation,
evidence, notifications and the commit. Never resolves an Incident.

Phase 4A is single-device: only Incidents raised by this same device are candidates.
Same-district / distance / multi-device correlation is deferred to Phase 4B+.
"""

from app.models import Incident
from app.models.incident import ACTIVE_STATUSES
from app.services import hazard_event_service
from app.services.seismic_state_persistence import save_state

MOTION_DISCLAIMER = ('Prototype motion sensor evidence. Not a certified earthquake detection, '
                     'not a prediction and no magnitude.')


def _source_reference(device):
    return f'device_{device.id}'


def find_active_incident_for_device(device):
    """Active earthquake Incident raised by this same device, or None. No time window, no cooldown."""
    return Incident.query.filter(
        Incident.event_type == 'earthquake',
        Incident.source == 'iot',
        Incident.source_reference == _source_reference(device),
        Incident.status.in_(ACTIVE_STATUSES),
    ).order_by(Incident.detected_at.desc()).first()


def correlate_device_event(device, device_event, assessment, transition):
    """Apply the transition's Incident consequence. Returns (incident, created) or None.

    Only event_started can create or attach. Continuation, gap and gap resume keep the
    current association untouched. event_ended clears it (the Incident stays as it is).
    The caller must have claimed the event start (claim_event_start) first.
    """
    if transition.event_ended:
        device_event.active_incident_id = None
        return None
    if not transition.event_started:
        return None

    def link(incident):
        # Same transaction as the Incident row / evidence it points to.
        device_event.active_incident_id = incident.id
        save_state(device.id, device_event)

    existing = find_active_incident_for_device(device)
    if existing:
        link(existing)
        # severity=None: a new episode is evidence, never an automatic escalation
        hazard_event_service.add_evidence(existing, None, _source_reference(device))
        return existing, False

    has_coords = device.latitude is not None and device.longitude is not None
    incident = hazard_event_service.create_hazard_event(
        event_type='earthquake',
        severity=assessment.severity,
        source='iot',
        district_id=device.district_id,
        latitude=device.latitude if has_coords else None,
        longitude=device.longitude if has_coords else None,
        location=device.location_description,
        title=f'Abnormal ground motion signal: {device.name}',
        description=f'{assessment.reasons[0]}. {MOTION_DISCLAIMER}',
        source_reference=_source_reference(device),
        before_commit=link,
    )
    return incident, True
