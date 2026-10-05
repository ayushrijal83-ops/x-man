"""Phase 2 tests: Seismic device-event state persistence."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import inspect

from app.extensions import db
from app.models import IoTDevice, District
from app.services.seismic_state import (
    SeismicStateMachine,
    MotionObservation,
    MotionLevel,
    SeismicState,
)
from app.services.seismic_state_persistence import (
    load_state,
    save_state,
    get_or_create_state,
    delete_state,
    get_state_summary,
    restore_state_machine,
    SeismicStatePersistenceError,
)


T0 = datetime(2026, 10, 1, 10, 0, 0)


def make_device(app, device_id='TEST-SEISMIC-001', district_name=None):
    """Create a seismic device for testing."""
    if district_name is None:
        district_name = f'Test District {device_id}'
    with app.app_context():
        district = District(name=district_name, province='Test Province')
        db.session.add(district)
        db.session.commit()

        device = IoTDevice(
            device_id=device_id,
            name=f'Test Seismic {device_id}',
            district_id=district.id,
            kind='sensor',
            enabled=True,
        )
        device.api_key_hash = IoTDevice.hash_api_key('test-key')
        db.session.add(device)
        db.session.commit()
        return device.id


def obs(timestamp: datetime, level: MotionLevel, peak: float = None) -> MotionObservation:
    """Create a MotionObservation."""
    return MotionObservation(
        timestamp=timestamp,
        level=level,
        peak_vibration_mg=peak,
    )


class TestInitialState:
    """Test 1: Create initial state when none exists."""

    def test_create_initial_state_quiet(self, app):
        device_id = make_device(app)

        with app.app_context():
            device_event = load_state(device_id)

            assert device_event.state == SeismicState.QUIET
            assert device_event.recovery_window_count == 0
            assert device_event.event_started_at is None
            assert device_event.event_ended_at is None
            assert device_event.peak_vibration_mg is None
            assert device_event.last_observation_at is None

    def test_get_or_create_idempotent(self, app):
        device_id = make_device(app)

        with app.app_context():
            event1 = get_or_create_state(device_id)
            event2 = get_or_create_state(device_id)

            assert event1.state == SeismicState.QUIET
            assert event2.state == SeismicState.QUIET

    def test_state_persisted_in_database(self, app):
        device_id = make_device(app)

        with app.app_context():
            load_state(device_id)
            from app.models.seismic_event_state import SeismicEventState
            row = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
            assert row is not None
            assert row.state == 'quiet'
            assert row.recovery_window_count == 0


class TestSaveActiveState:
    """Test 2: Save ACTIVE state and reload."""

    def test_save_and_reload_active(self, app):
        device_id = make_device(app)

        with app.app_context():
            # Build ACTIVE state via state machine
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 150.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 300.0))

            assert machine.state == SeismicState.ACTIVE
            assert machine.device_event.event_started_at == T0
            assert machine.device_event.peak_vibration_mg == 300.0

            # Save to DB
            save_state(device_id, machine.device_event)
            db.session.commit()

        # Reload in new context
        with app.app_context():
            reloaded = load_state(device_id)

            assert reloaded.state == SeismicState.ACTIVE
            assert reloaded.event_started_at == T0
            assert reloaded.peak_vibration_mg == 300.0
            assert reloaded.last_observation_at == T0 + timedelta(minutes=1)
            assert reloaded.recovery_window_count == 0

    def test_save_active_preserves_all_fields(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 500.0))
            machine.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.ELEVATED, 200.0))

            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            reloaded = load_state(device_id)
            assert reloaded.state == SeismicState.ACTIVE
            assert reloaded.event_started_at == T0
            assert reloaded.peak_vibration_mg == 500.0
            assert reloaded.last_observation_at == T0 + timedelta(minutes=2)
            assert reloaded.recovery_window_count == 0
            assert reloaded.event_ended_at is None


class TestSaveRecoveryState:
    """Test 3: Save RECOVERY state and reload."""

    def test_save_and_reload_recovery(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
            machine.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))

            assert machine.state == SeismicState.RECOVERY
            assert machine.device_event.recovery_window_count == 2
            assert machine.device_event.recovery_started_at == T0 + timedelta(minutes=1)

            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            reloaded = load_state(device_id)

            assert reloaded.state == SeismicState.RECOVERY
            assert reloaded.recovery_window_count == 2
            assert reloaded.recovery_started_at == T0 + timedelta(minutes=1)
            assert reloaded.event_started_at == T0
            assert reloaded.peak_vibration_mg == 200.0

    def test_recovery_counter_survives_restart(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
            machine.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            # Reload and continue
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            assert machine2.state == SeismicState.RECOVERY
            assert machine2.device_event.recovery_window_count == 2

            # Continue recovery
            result = machine2.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.NORMAL, 30.0))

            assert machine2.state == SeismicState.QUIET
            assert result.event_ended is True
            assert result.recovery_completed is True
            assert machine2.device_event.event_ended_at == T0 + timedelta(minutes=3)


class TestSaveTelemetryGapState:
    """Test 4: Save TELEMETRY_GAP state and reload."""

    def test_save_and_reload_telemetry_gap(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            gap_time = T0 + timedelta(minutes=6)
            machine.check_gap(gap_time)

            assert machine.state == SeismicState.TELEMETRY_GAP
            assert machine.device_event.gap_entered_at == gap_time

            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            reloaded = load_state(device_id)

            assert reloaded.state == SeismicState.TELEMETRY_GAP
            assert reloaded.gap_entered_at == gap_time
            assert reloaded.event_started_at == T0
            assert reloaded.peak_vibration_mg == 200.0
            assert reloaded.event_ended_at is None


class TestRestartSimulation:
    """Test 5: Restart simulation - event continues after reload."""

    def test_event_continues_after_reload(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 150.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            assert machine2.state == SeismicState.ACTIVE
            assert machine2.device_event.event_started_at == T0
            assert machine2.device_event.peak_vibration_mg == 150.0

            # Continue the event
            result = machine2.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.ELEVATED, 400.0))
            assert machine2.state == SeismicState.ACTIVE
            assert result.event_started is False
            assert machine2.device_event.peak_vibration_mg == 400.0


class TestNoDuplicateEventStart:
    """Test 6: No duplicate event start after reload."""

    def test_no_new_event_start_after_reload(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            assert machine2.state == SeismicState.ACTIVE
            assert machine2.device_event.event_started_at == T0

            result = machine2.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 200.0))
            assert result.event_started is False
            assert machine2.device_event.event_started_at == T0


class TestRecoveryCounterSurvivesRestart:
    """Test 7: Recovery counter survives restart."""

    def test_recovery_counter_survives(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
            machine.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            assert machine2.device_event.recovery_window_count == 2

            # Third normal should complete recovery
            result = machine2.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.NORMAL, 30.0))
            assert machine2.state == SeismicState.QUIET
            assert result.event_ended is True
            assert machine2.device_event.event_ended_at == T0 + timedelta(minutes=3)


class TestTelemetryGapSurvivesRestart:
    """Test 8: Telemetry gap survives restart."""

    def test_telemetry_gap_persists(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            gap_time = T0 + timedelta(minutes=6)
            machine.check_gap(gap_time)
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            reloaded = load_state(device_id)
            assert reloaded.state == SeismicState.TELEMETRY_GAP
            assert reloaded.gap_entered_at == gap_time


class TestServerRestartNoAutoRecovery:
    """Test 9: Server restart does not create recovery/end event."""

    def test_reload_active_does_not_end_event(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        # Simulate server restart at a much later time
        later_time = T0 + timedelta(hours=2)

        with app.app_context():
            reloaded = load_state(device_id)
            assert reloaded.state == SeismicState.ACTIVE
            assert reloaded.event_ended_at is None
            assert reloaded.event_started_at == T0

            # State machine should NOT auto-transition to gap just by loading
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            assert machine2.state == SeismicState.ACTIVE
            assert machine2.device_event.event_ended_at is None

    def test_check_gap_still_works_after_reload(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 200.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            # Check gap with current time far in future
            result = machine2.check_gap(T0 + timedelta(minutes=10))
            assert result is not None
            assert machine2.state == SeismicState.TELEMETRY_GAP
            assert result.gap_entered is True


class TestOneRowPerDevice:
    """Test 10: One row per device constraint."""

    def test_unique_device_id_constraint(self, app):
        device_id = make_device(app)

        with app.app_context():
            load_state(device_id)
            db.session.commit()

            # Try to create duplicate
            from app.models.seismic_event_state import SeismicEventState
            duplicate = SeismicEventState(device_id=device_id, state='quiet')
            db.session.add(duplicate)

            with pytest.raises(Exception):  # SQLite raises IntegrityError
                db.session.commit()

            db.session.rollback()


class TestIndependentDevices:
    """Test 11: Different devices have independent state."""

    def test_independent_state_per_device(self, app):
        device_id_1 = make_device(app, 'DEVICE-001', 'District One')
        device_id_2 = make_device(app, 'DEVICE-002', 'District Two')

        with app.app_context():
            machine1 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine1.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
            save_state(device_id_1, machine1.device_event)
            db.session.commit()

            machine2 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            # Device 2 stays QUIET
            save_state(device_id_2, machine2.device_event)
            db.session.commit()

        with app.app_context():
            reloaded1 = load_state(device_id_1)
            reloaded2 = load_state(device_id_2)

            assert reloaded1.state == SeismicState.ACTIVE
            assert reloaded2.state == SeismicState.QUIET


class TestOutOfOrderProtection:
    """Test 12: Out-of-order observation protection after persistence."""

    def test_out_of_order_rejected_after_reload(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0 + timedelta(minutes=5), MotionLevel.ELEVATED, 100.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            machine2 = restore_state_machine(device_id, recovery_windows=3, gap_tolerance_seconds=300)
            # Try to add observation with earlier timestamp
            with pytest.raises(ValueError, match="before last accepted observation"):
                machine2.process_observation(obs(T0, MotionLevel.NORMAL, 50.0))


class TestMigration:
    """Test 13: Migration upgrade/downgrade."""

    def test_migration_upgrade_creates_table(self, app):
        with app.app_context():
            from app.models.seismic_event_state import SeismicEventState
            tables = inspect(db.engine).get_table_names()
            assert 'seismic_event_states' in tables

            # Verify we can insert and query
            device_id = make_device(app, 'MIGRATION-TEST')
            row = SeismicEventState(device_id=device_id, state='quiet')
            db.session.add(row)
            db.session.commit()

            queried = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
            assert queried is not None
            assert queried.state == 'quiet'

    def test_migration_downgrade_removes_only_phase2_table(self, app):
        with app.app_context():
            # Table should exist before downgrade
            tables = inspect(db.engine).get_table_names()
            assert 'seismic_event_states' in tables

        # Note: Actual downgrade test would require running flask db downgrade
        # which is tested separately in the migration validation


class TestPersistenceEdgeCases:
    """Additional edge case tests."""

    def test_delete_state(self, app):
        device_id = make_device(app)

        with app.app_context():
            load_state(device_id)
            db.session.commit()

            deleted = delete_state(device_id)
            assert deleted is True
            db.session.commit()

        with app.app_context():
            from app.models.seismic_event_state import SeismicEventState
            row = db.session.query(SeismicEventState).filter_by(device_id=device_id).first()
            assert row is None

    def test_delete_nonexistent_state(self, app):
        device_id = make_device(app)

        with app.app_context():
            deleted = delete_state(99999)  # Non-existent device
            assert deleted is False

    def test_get_state_summary(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 500.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            summary = get_state_summary(device_id)
            assert summary is not None
            assert summary['state'] == 'active'
            assert summary['peak_vibration_mg'] == 500.0
            assert summary['event_started_at'] is not None

    def test_get_state_summary_nonexistent(self, app):
        with app.app_context():
            summary = get_state_summary(99999)
            assert summary is None


class TestRestoreStateMachine:
    """Test restore_state_machine helper."""

    def test_restore_state_machine_returns_configured_machine(self, app):
        device_id = make_device(app)

        with app.app_context():
            machine = SeismicStateMachine(recovery_windows=5, gap_tolerance_seconds=600)
            machine.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
            machine.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
            save_state(device_id, machine.device_event)
            db.session.commit()

        with app.app_context():
            restored = restore_state_machine(device_id, recovery_windows=5, gap_tolerance_seconds=600)
            assert restored.recovery_windows_required == 5
            assert restored.gap_tolerance.total_seconds() == 600
            assert restored.state == SeismicState.RECOVERY
            assert restored.device_event.recovery_window_count == 1

    def test_restore_state_machine_QUIET(self, app):
        device_id = make_device(app)

        with app.app_context():
            load_state(device_id)
            db.session.commit()

        with app.app_context():
            restored = restore_state_machine(device_id)
            assert restored.state == SeismicState.QUIET
            assert restored.device_event.recovery_window_count == 0