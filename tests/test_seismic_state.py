"""Tests for Phase 1 seismic device-event state machine."""

import pytest
from datetime import datetime, timedelta

from app.services.seismic_state import (
    SeismicStateMachine,
    MotionObservation,
    MotionLevel,
    SeismicState,
    StateTransition,
    create_motion_observation,
    motion_level_from_risk_assessment,
)
from types import SimpleNamespace


T0 = datetime(2026, 10, 1, 10, 0, 0)


def make_assessment(level: str, **evidence):
    """Create a mock RiskAssessment-like object."""
    default_evidence = {
        "max_vibration_mg": 100.0,
        "vibration_over_threshold": 1,
        "tilt_change_deg": None,
    }
    default_evidence.update(evidence)
    return SimpleNamespace(level=level, evidence=default_evidence)


def obs(timestamp: datetime, level: MotionLevel, peak: float = None) -> MotionObservation:
    """Create a MotionObservation."""
    return MotionObservation(
        timestamp=timestamp,
        level=level,
        peak_vibration_mg=peak,
    )


class TestSeismicStateMachine:
    """Core state machine behavior tests."""

    def test_quiet_remains_quiet_on_normal(self):
        """Scenario 1: Quiet remains quiet on normal observations."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        for i in range(3):
            result = sm.process_observation(obs(T0 + timedelta(minutes=i), MotionLevel.NORMAL, 50.0))

        assert sm.state == SeismicState.QUIET
        assert not sm.device_event.is_event_active()
        assert sm.device_event.event_started_at is None
        assert all(not r.event_started for r in [result])

    def test_first_abnormal_starts_event(self):
        """Scenario 2: First abnormal observation starts event."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        result = sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))

        assert sm.state == SeismicState.ACTIVE
        assert sm.device_event.is_event_active()
        assert sm.device_event.event_started_at == T0
        assert result.event_started is True
        assert result.new_state == SeismicState.ACTIVE

    def test_continuous_abnormal_is_one_event(self):
        """Scenario 3: Continuous abnormal motion is one event."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 85.0))
        start_count = 0
        for i in range(1, 4):
            result = sm.process_observation(obs(T0 + timedelta(minutes=i), MotionLevel.ELEVATED, 100.0 + i * 10))
            if result.event_started:
                start_count += 1

        assert sm.state == SeismicState.ACTIVE
        assert start_count == 0  # No additional start signals
        assert sm.device_event.event_started_at == T0

    def test_peak_is_tracked(self):
        """Scenario 4: Peak vibration is tracked."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 85.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.ELEVATED, 500.0))
        sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 120.0))

        assert sm.device_event.peak_vibration_mg == 500.0

    def test_recovery_begins_on_normal_after_active(self):
        """Scenario 5: Recovery begins on normal after active."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))

        assert sm.state == SeismicState.RECOVERY
        assert sm.device_event.recovery_window_count == 1
        assert sm.device_event.recovery_started_at == T0 + timedelta(minutes=1)
        assert result.recovery_started is True

    def test_recovery_completes_after_required_windows(self):
        """Scenario 6: Recovery completes after required windows (default 3)."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
        result = sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.NORMAL, 30.0))

        assert sm.state == SeismicState.QUIET
        assert not sm.device_event.is_event_active()
        assert sm.device_event.event_ended_at == T0 + timedelta(minutes=3)
        assert result.event_ended is True
        assert result.recovery_completed is True

    def test_recovery_interrupted_by_abnormal(self):
        """Scenario 7: Recovery interrupted by abnormal returns to active."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
        result = sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 200.0))

        assert sm.state == SeismicState.ACTIVE
        assert sm.device_event.recovery_window_count == 0
        assert sm.device_event.recovery_started_at is None
        assert sm.device_event.peak_vibration_mg == 200.0

    def test_recovery_interruption_does_not_create_second_event(self):
        """Scenario 8: Recovery interruption must NOT create a second event."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
        result = sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 200.0))

        # Count total event_started signals across all transitions
        start_count = 1  # First observation started it
        # Re-process to count
        sm2 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
        start_count = 0
        for r in [
            sm2.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0)),
            sm2.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0)),
            sm2.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0)),
            sm2.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 200.0)),
        ]:
            if r.event_started:
                start_count += 1

        assert start_count == 1  # Only one event start

    def test_telemetry_gap_is_not_recovery(self):
        """Scenario 9: Telemetry gap is not recovery."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.check_gap(T0 + timedelta(minutes=6))  # 6 min gap > 5 min tolerance

        assert sm.state == SeismicState.TELEMETRY_GAP
        assert sm.device_event.is_event_active()
        assert sm.device_event.event_ended_at is None
        assert result is not None
        assert result.gap_entered is True

    def test_abnormal_after_gap_continues_event(self):
        """Scenario 10: Abnormal telemetry after gap continues event."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.check_gap(T0 + timedelta(minutes=6))  # Enter gap
        result = sm.process_observation(obs(T0 + timedelta(minutes=7), MotionLevel.ELEVATED, 150.0))

        assert sm.state == SeismicState.ACTIVE
        assert result.gap_resumed is True
        assert result.abnormal_during_gap is True
        assert result.event_started is False  # No new event start
        assert sm.device_event.event_started_at == T0  # Original start time preserved

    def test_normal_after_gap_enters_recovery(self):
        """Scenario 11: Normal telemetry after gap enters recovery based on actual evidence."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.check_gap(T0 + timedelta(minutes=6))  # Enter gap
        result = sm.process_observation(obs(T0 + timedelta(minutes=7), MotionLevel.NORMAL, 40.0))

        assert sm.state == SeismicState.RECOVERY
        assert result.gap_resumed is True
        assert result.normal_during_gap is True
        assert result.recovery_started is True
        assert sm.device_event.recovery_window_count == 1

    def test_large_timestamp_jump_deterministic(self):
        """Scenario 12: Large timestamp jump handled deterministically."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        # Jump 1 hour forward - should enter gap
        result = sm.check_gap(T0 + timedelta(hours=1))

        assert sm.state == SeismicState.TELEMETRY_GAP
        assert result is not None
        assert result.gap_entered is True

    def test_out_of_order_timestamp_raises(self):
        """Scenario 13: Out-of-order timestamps are rejected."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0 + timedelta(minutes=5), MotionLevel.ELEVATED, 100.0))

        with pytest.raises(ValueError, match="before last accepted observation"):
            sm.process_observation(obs(T0, MotionLevel.NORMAL, 50.0))

    def test_repeated_identical_timestamp_accepted(self):
        """Scenario 14: Repeated identical timestamps are accepted (deterministic)."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.process_observation(obs(T0, MotionLevel.ELEVATED, 120.0))

        assert sm.state == SeismicState.ACTIVE
        assert sm.device_event.peak_vibration_mg == 120.0

    def test_extreme_vibration_values(self):
        """Scenario 15: Extreme vibration values handled."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.NORMAL, 0.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 85.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.ELEVATED, 1000.0))
        sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 999999.0))

        assert sm.device_event.peak_vibration_mg == 999999.0
        assert sm.state == SeismicState.ACTIVE

    def test_recovery_completes_exactly_at_threshold(self):
        """Recovery completes exactly at the required window count."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))  # 1/3
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))  # 2/3
        assert sm.state == SeismicState.RECOVERY
        assert sm.device_event.recovery_window_count == 2

        result = sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.NORMAL, 30.0))  # 3/3
        assert sm.state == SeismicState.QUIET
        assert result.recovery_completed is True

    def test_recovery_counter_resets_on_abnormal(self):
        """Recovery counter resets to 0 when abnormal motion returns."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
        assert sm.device_event.recovery_window_count == 2

        sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.ELEVATED, 150.0))
        assert sm.device_event.recovery_window_count == 0

    def test_check_gap_no_transition_before_tolerance(self):
        """check_gap does not transition before gap tolerance is reached."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.check_gap(T0 + timedelta(minutes=4))  # 4 min < 5 min tolerance

        assert result is None
        assert sm.state == SeismicState.ACTIVE

    def test_check_gap_transitions_at_tolerance(self):
        """check_gap transitions exactly at gap tolerance."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.check_gap(T0 + timedelta(minutes=5))  # Exactly 5 min

        assert result is not None
        assert sm.state == SeismicState.TELEMETRY_GAP
        assert result.gap_entered is True

    def test_check_gap_from_recovery_state(self):
        """check_gap also works from RECOVERY state."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        result = sm.check_gap(T0 + timedelta(minutes=6))

        assert sm.state == SeismicState.TELEMETRY_GAP
        assert result.gap_entered is True

    def test_quiet_state_no_gap_transition(self):
        """QUIET state never transitions to TELEMETRY_GAP via check_gap."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.NORMAL, 50.0))
        result = sm.check_gap(T0 + timedelta(hours=1))

        assert result is None
        assert sm.state == SeismicState.QUIET

    def test_uncharacterized_level_does_not_start_event(self):
        """UNCHARACTERIZED level does not start an event from QUIET."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        result = sm.process_observation(obs(T0, MotionLevel.UNCHARACTERIZED, None))

        assert sm.state == SeismicState.QUIET
        assert result.event_started is False

    def test_uncharacterized_in_active_remains_active(self):
        """UNCHARACTERIZED in ACTIVE keeps ACTIVE state."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.UNCHARACTERIZED, None))

        assert sm.state == SeismicState.ACTIVE

    def test_get_status_summary(self):
        """get_status_summary returns correct structure."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        summary = sm.get_status_summary()
        assert summary["state"] == "quiet"
        assert summary["event_active"] is False
        assert summary["recovery_windows_required"] == 3

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        summary = sm.get_status_summary()
        assert summary["state"] == "active"
        assert summary["event_active"] is True
        assert summary["event_started_at"] is not None
        assert summary["peak_vibration_mg"] == 100.0


class TestMotionObservationHelpers:
    """Tests for helper functions."""

    def test_motion_level_from_risk_assessment(self):
        """motion_level_from_risk_assessment maps correctly."""
        assert motion_level_from_risk_assessment(make_assessment("elevated_motion")) == MotionLevel.ELEVATED
        assert motion_level_from_risk_assessment(make_assessment("normal_motion")) == MotionLevel.NORMAL
        assert motion_level_from_risk_assessment(make_assessment("uncharacterized")) == MotionLevel.UNCHARACTERIZED
        assert motion_level_from_risk_assessment(make_assessment("unknown_level")) == MotionLevel.UNCHARACTERIZED

    def test_create_motion_observation_from_assessment(self):
        """create_motion_observation extracts evidence correctly."""
        assessment = make_assessment(
            "elevated_motion",
            max_vibration_mg=500.0,
            vibration_over_threshold=3,
            tilt_change_deg=2.5,
        )
        obs = create_motion_observation(T0, assessment)

        assert obs.timestamp == T0
        assert obs.level == MotionLevel.ELEVATED
        assert obs.peak_vibration_mg == 500.0
        assert obs.vibration_over_threshold == 3
        assert obs.tilt_change_deg == 2.5

    def test_create_motion_observation_overrides(self):
        """create_motion_observation allows explicit overrides."""
        assessment = make_assessment("elevated_motion", max_vibration_mg=100.0)
        obs = create_motion_observation(T0, assessment, peak_vibration_mg=999.0, vibration_over_threshold=5)

        assert obs.peak_vibration_mg == 999.0
        assert obs.vibration_over_threshold == 5


class TestConfigurableParameters:
    """Tests for configurable recovery windows and gap tolerance."""

    def test_custom_recovery_windows(self):
        """Custom recovery window count works."""
        sm = SeismicStateMachine(recovery_windows=5, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        for i in range(1, 6):
            result = sm.process_observation(obs(T0 + timedelta(minutes=i), MotionLevel.NORMAL, 50.0))
            if i < 5:
                assert sm.state == SeismicState.RECOVERY
            else:
                assert sm.state == SeismicState.QUIET
                assert result.recovery_completed is True

    def test_custom_gap_tolerance(self):
        """Custom gap tolerance works."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=60)  # 1 minute

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        result = sm.check_gap(T0 + timedelta(seconds=30))
        assert result is None  # 30s < 60s

        result = sm.check_gap(T0 + timedelta(seconds=90))
        assert result is not None  # 90s > 60s
        assert sm.state == SeismicState.TELEMETRY_GAP


class TestEdgeCases:
    """Edge case and robustness tests."""

    def test_no_observations_then_gap_check(self):
        """check_gap with no observations returns None."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
        result = sm.check_gap(T0)
        assert result is None

    def test_normal_observation_does_not_update_peak(self):
        """Normal observations don't update peak."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 500.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 600.0))  # Higher but normal
        assert sm.device_event.peak_vibration_mg == 500.0

    def test_peak_only_updates_on_higher(self):
        """Peak only updates when new value is higher."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 500.0))
        sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.ELEVATED, 300.0))
        sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.ELEVATED, 700.0))
        assert sm.device_event.peak_vibration_mg == 700.0

    def test_event_duration_calculation(self):
        """current_event_duration calculates correctly."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        assert sm.device_event.current_event_duration(T0) is None

        sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        duration = sm.device_event.current_event_duration(T0 + timedelta(minutes=5))
        assert duration == timedelta(minutes=5)

        sm.process_observation(obs(T0 + timedelta(minutes=5), MotionLevel.NORMAL, 50.0))
        sm.process_observation(obs(T0 + timedelta(minutes=6), MotionLevel.NORMAL, 40.0))
        sm.process_observation(obs(T0 + timedelta(minutes=7), MotionLevel.NORMAL, 30.0))
        duration = sm.device_event.current_event_duration(T0 + timedelta(minutes=10))
        assert duration == timedelta(minutes=7)  # Ended at minute 7

    def test_multiple_state_machines_independent(self):
        """Multiple state machines operate independently."""
        sm1 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
        sm2 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        sm1.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm2.process_observation(obs(T0, MotionLevel.NORMAL, 50.0))

        assert sm1.state == SeismicState.ACTIVE
        assert sm2.state == SeismicState.QUIET

    def test_invalid_recovery_windows_raises(self):
        """Invalid recovery_windows raises ValueError."""
        with pytest.raises(ValueError, match="recovery_windows must be >= 1"):
            SeismicStateMachine(recovery_windows=0)

    def test_invalid_gap_tolerance_raises(self):
        """Invalid gap_tolerance_seconds raises ValueError."""
        with pytest.raises(ValueError, match="gap_tolerance_seconds must be >= 0"):
            SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=-1)

    def test_state_transition_signals_complete(self):
        """All StateTransition signals are properly set."""
        sm = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)

        # QUIET -> ACTIVE
        r1 = sm.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        assert r1.event_started
        assert not r1.event_ended
        assert not r1.recovery_started
        assert not r1.recovery_completed
        assert not r1.gap_entered
        assert not r1.gap_resumed

        # ACTIVE -> RECOVERY
        r2 = sm.process_observation(obs(T0 + timedelta(minutes=1), MotionLevel.NORMAL, 50.0))
        assert r2.recovery_started
        assert not r2.event_started
        assert not r2.event_ended

        # RECOVERY -> RECOVERY
        r3 = sm.process_observation(obs(T0 + timedelta(minutes=2), MotionLevel.NORMAL, 40.0))
        assert not any([r3.event_started, r3.event_ended, r3.recovery_started, r3.recovery_completed, r3.gap_entered, r3.gap_resumed])

        # RECOVERY -> QUIET
        r4 = sm.process_observation(obs(T0 + timedelta(minutes=3), MotionLevel.NORMAL, 30.0))
        assert r4.event_ended
        assert r4.recovery_completed

        # QUIET -> TELEMETRY_GAP not possible directly

        # ACTIVE -> TELEMETRY_GAP via check_gap
        sm2 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
        sm2.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        r5 = sm2.check_gap(T0 + timedelta(minutes=6))
        assert r5.gap_entered

        # TELEMETRY_GAP -> ACTIVE
        r6 = sm2.process_observation(obs(T0 + timedelta(minutes=7), MotionLevel.ELEVATED, 150.0))
        assert r6.gap_resumed
        assert r6.abnormal_during_gap
        assert not r6.event_started

        # TELEMETRY_GAP -> RECOVERY
        sm3 = SeismicStateMachine(recovery_windows=3, gap_tolerance_seconds=300)
        sm3.process_observation(obs(T0, MotionLevel.ELEVATED, 100.0))
        sm3.check_gap(T0 + timedelta(minutes=6))
        r7 = sm3.process_observation(obs(T0 + timedelta(minutes=7), MotionLevel.NORMAL, 40.0))
        assert r7.gap_resumed
        assert r7.normal_during_gap
        assert r7.recovery_started