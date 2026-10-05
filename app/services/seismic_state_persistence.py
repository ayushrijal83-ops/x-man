"""Seismic device-event state persistence adapter (Phase 2).

Translates between the Phase 1 pure state machine and the SeismicEventState
database model. No transition logic — only serialization/deserialization.
"""

from datetime import datetime
from typing import Optional
import threading

from sqlalchemy.exc import IntegrityError, OperationalError

from app.extensions import db
from app.models.seismic_event_state import SeismicEventState
from app.services.seismic_state import (
    SeismicStateMachine,
    SeismicDeviceEvent,
    SeismicState,
    MotionLevel,
)


class SeismicStatePersistenceError(Exception):
    """Raised when persistence operations fail."""
    pass


# Thread-local mutex per device_id for SQLite concurrency control
# This is a fallback for databases that don't support SELECT FOR UPDATE
_seismic_state_mutex = threading.Lock()
_seismic_state_device_locks = {}


def _get_device_lock(device_id: int) -> threading.Lock:
    """Get or create a per-device lock for SQLite concurrency control."""
    with _seismic_state_mutex:
        if device_id not in _seismic_state_device_locks:
            _seismic_state_device_locks[device_id] = threading.Lock()
        return _seismic_state_device_locks[device_id]


def _supports_select_for_update() -> bool:
    """Check if the current database dialect supports SELECT FOR UPDATE."""
    dialect_name = db.engine.dialect.name
    # MySQL, PostgreSQL, and MariaDB support FOR UPDATE
    # SQLite does not support FOR UPDATE in a useful way for this race condition
    return dialect_name in ('mysql', 'postgresql', 'mariadb')


def _db_state_to_enum(db_state: str) -> SeismicState:
    """Convert database state string to SeismicState enum."""
    mapping = {
        'quiet': SeismicState.QUIET,
        'active': SeismicState.ACTIVE,
        'recovery': SeismicState.RECOVERY,
        'telemetry_gap': SeismicState.TELEMETRY_GAP,
    }
    return mapping.get(db_state, SeismicState.QUIET)


def _db_level_to_enum(db_level: Optional[str]) -> Optional[MotionLevel]:
    """Convert database level string to MotionLevel enum."""
    if db_level is None:
        return None
    mapping = {
        'normal': MotionLevel.NORMAL,
        'elevated': MotionLevel.ELEVATED,
        'uncharacterized': MotionLevel.UNCHARACTERIZED,
    }
    return mapping.get(db_level)


def _enum_to_db_state(state: SeismicState) -> str:
    """Convert SeismicState enum to database string."""
    return state.value


def _enum_to_db_level(level: Optional[MotionLevel]) -> Optional[str]:
    """Convert MotionLevel enum to database string."""
    if level is None:
        return None
    return level.value


def load_state(device_id: int) -> SeismicDeviceEvent:
    """Load persistent state for a device, creating initial QUIET state if none exists.

    Returns a SeismicDeviceEvent populated from the database.
    Does NOT commit — caller owns the transaction.

    Concurrency safety:
    - For MySQL/PostgreSQL/MariaDB: uses SELECT FOR UPDATE to lock the row
    - For SQLite: uses a per-device mutex to serialize access
    - Handles race condition where row is created between SELECT and INSERT
    """
    # Maximum retries for handling race conditions
    max_retries = 3

    for attempt in range(max_retries):
        try:
            if _supports_select_for_update():
                # For MySQL/PostgreSQL/MariaDB: use SELECT FOR UPDATE to lock the row
                db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).with_for_update(nowait=True).first()
            else:
                # SQLite: use per-device mutex to serialize access
                device_lock = _get_device_lock(device_id)
                with device_lock:
                    db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()

            if db_state is None:
                # No persistent state: create initial QUIET state in DB
                db_state = SeismicEventState(device_id=device_id, state='quiet')
                db.session.add(db_state)
                db.session.flush()

            return _db_row_to_device_event(db_state)

        except OperationalError:
            # Database doesn't support NOWAIT (some MySQL configurations)
            # Fall back to waiting lock
            if _supports_select_for_update():
                try:
                    db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).with_for_update().first()
                    if db_state is None:
                        db_state = SeismicEventState(device_id=device_id, state='quiet')
                        db.session.add(db_state)
                        db.session.flush()
                    return _db_row_to_device_event(db_state)
                except OperationalError:
                    # Still fails, try without lock as last resort
                    pass
            # For SQLite or if FOR UPDATE failed, fall through to mutex approach
            device_lock = _get_device_lock(device_id)
            with device_lock:
                db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
                if db_state is None:
                    db_state = SeismicEventState(device_id=device_id, state='quiet')
                    db.session.add(db_state)
                    db.session.flush()
                return _db_row_to_device_event(db_state)

        except IntegrityError:
            # Race condition: another transaction created the row between our SELECT and INSERT
            db.session.rollback()
            if attempt < max_retries - 1:
                continue  # Retry
            raise SeismicStatePersistenceError(f"Failed to load/create state for device {device_id} after {max_retries} attempts") from None

    # Should not reach here
    raise SeismicStatePersistenceError(f"Failed to load/create state for device {device_id} after {max_retries} attempts")


def _db_row_to_device_event(db_state: SeismicEventState) -> SeismicDeviceEvent:
    """Convert a SeismicEventState DB row to a SeismicDeviceEvent in-memory object."""
    event = SeismicDeviceEvent()
    event.state = _db_state_to_enum(db_state.state)
    event.event_started_at = db_state.event_started_at
    event.event_ended_at = db_state.event_ended_at
    event.peak_vibration_mg = db_state.peak_vibration_mg
    event.last_observation_at = db_state.last_observation_at
    event.recovery_window_count = db_state.recovery_window_count
    event.recovery_started_at = db_state.recovery_started_at
    event.gap_entered_at = db_state.gap_entered_at
    event.active_incident_id = db_state.active_incident_id
    return event


def save_state(device_id: int, device_event: SeismicDeviceEvent) -> SeismicEventState:
    """Save the in-memory device event state to the database.

    Returns the updated SeismicEventState row.
    Does NOT commit — caller owns the transaction.
    """
    db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()

    if db_state is None:
        db_state = SeismicEventState(device_id=device_id)
        db.session.add(db_state)

    db_state.state = _enum_to_db_state(device_event.state)
    db_state.event_started_at = device_event.event_started_at
    db_state.event_ended_at = device_event.event_ended_at
    db_state.peak_vibration_mg = device_event.peak_vibration_mg
    db_state.last_observation_at = device_event.last_observation_at
    # last_observation_level not tracked in Phase 1; leave as-is
    db_state.recovery_window_count = device_event.recovery_window_count
    db_state.recovery_started_at = device_event.recovery_started_at
    # recovery_confirmed_at = event_ended_at when recovery completes
    db_state.recovery_confirmed_at = device_event.event_ended_at
    db_state.gap_entered_at = device_event.gap_entered_at
    # Phase 4A: active incident association
    db_state.active_incident_id = device_event.active_incident_id

    db.session.flush()
    return db_state


def get_or_create_state(device_id: int) -> SeismicDeviceEvent:
    """Convenience: load or create initial state for a device.

    Equivalent to load_state() but name emphasizes idempotency.
    """
    return load_state(device_id)


def delete_state(device_id: int) -> bool:
    """Delete persistent state for a device. Returns True if deleted."""
    db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
    if db_state is None:
        return False
    db.session.delete(db_state)
    db.session.flush()
    return True


def get_state_summary(device_id: int) -> Optional[dict]:
    """Get a summary of the persistent state for debugging/monitoring."""
    db_state = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
    if db_state is None:
        return None
    return db_state.to_dict()


def restore_state_machine(
    device_id: int,
    recovery_windows: int = 3,
    gap_tolerance_seconds: int = 300,
) -> SeismicStateMachine:
    """Restore a fully initialized SeismicStateMachine from persistent state.

    This is the main entry point for Phase 3+ integration.
    """
    device_event = load_state(device_id)
    machine = SeismicStateMachine(
        recovery_windows=recovery_windows,
        gap_tolerance_seconds=gap_tolerance_seconds,
    )
    # Replace the machine's internal device_event with the loaded one
    machine._device_event = device_event
    return machine

def claim_event_start(device_id: int) -> bool:
    """Phase 4A: atomically claim QUIET -> ACTIVE for this device. Does NOT commit.

    Compare-and-set at the database: the UPDATE matches only while the persisted row is still
    QUIET, and the row/write lock is held until the caller commits. Of two concurrent requests
    that both loaded QUIET, exactly one gets True; the loser must not start a second Device Event
    (nor correlate a second Incident). Works on SQLite, PostgreSQL and MySQL alike.
    """
    claimed = db.session.query(SeismicEventState) \
        .filter(SeismicEventState.device_id == device_id, SeismicEventState.state == 'quiet') \
        .update({'state': 'active'}, synchronize_session=False)
    return claimed == 1
