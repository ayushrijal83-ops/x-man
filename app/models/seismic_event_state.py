"""Seismic device-event persistent state (Phase 2).

Stores the Phase 1 state machine state for each seismic device.
One row per device. No transition logic here — that lives in the pure state machine.
"""

from datetime import datetime

from app.extensions import db
from app.models.iot_device import IoTDevice


class SeismicEventState(db.Model):
    """Persistent state for one seismic device's event detector."""
    __tablename__ = 'seismic_event_states'

    id = db.Column(db.Integer, primary_key=True)

    device_id = db.Column(
        db.Integer,
        db.ForeignKey('iot_devices.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True
    )

    state = db.Column(db.String(20), nullable=False, default='quiet')

    event_started_at = db.Column(db.DateTime, nullable=True)
    event_ended_at = db.Column(db.DateTime, nullable=True)

    peak_vibration_mg = db.Column(db.Float, nullable=True)

    last_observation_at = db.Column(db.DateTime, nullable=True)
    last_observation_level = db.Column(db.String(20), nullable=True)

    recovery_window_count = db.Column(db.Integer, nullable=False, default=0)
    recovery_started_at = db.Column(db.DateTime, nullable=True)
    recovery_confirmed_at = db.Column(db.DateTime, nullable=True)

    gap_entered_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    device = db.relationship('IoTDevice', backref=db.backref('seismic_state', uselist=False))

    def __repr__(self):
        return f'<SeismicEventState device={self.device_id} state={self.state}>'

    VALID_STATES = {'quiet', 'active', 'recovery', 'telemetry_gap'}
    VALID_LEVELS = {'normal', 'elevated', 'uncharacterized'}

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'state': self.state,
            'event_started_at': self.event_started_at.isoformat() if self.event_started_at else None,
            'event_ended_at': self.event_ended_at.isoformat() if self.event_ended_at else None,
            'peak_vibration_mg': self.peak_vibration_mg,
            'last_observation_at': self.last_observation_at.isoformat() if self.last_observation_at else None,
            'last_observation_level': self.last_observation_level,
            'recovery_window_count': self.recovery_window_count,
            'recovery_started_at': self.recovery_started_at.isoformat() if self.recovery_started_at else None,
            'recovery_confirmed_at': self.recovery_confirmed_at.isoformat() if self.recovery_confirmed_at else None,
            'gap_entered_at': self.gap_entered_at.isoformat() if self.gap_entered_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }