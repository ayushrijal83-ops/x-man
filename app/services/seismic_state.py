"""Seismic device-event state machine (Phase 1).

Pure, deterministic state machine for tracking a single seismic device's
abnormal-motion episode. No database, no Flask, no HTTP, no external deps.

States:
    QUIET          No active abnormal-motion event.
    ACTIVE         Device is experiencing an abnormal-motion event.
    RECOVERY       Normal evidence observed after ACTIVE; counting recovery windows.
    TELEMETRY_GAP  Telemetry stopped long enough that event continuity is uncertain.

Transitions are driven by MotionObservation inputs with timestamps.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class SeismicState(Enum):
    QUIET = "quiet"
    ACTIVE = "active"
    RECOVERY = "recovery"
    TELEMETRY_GAP = "telemetry_gap"


class MotionLevel(Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    UNCHARACTERIZED = "uncharacterized"


@dataclass(frozen=True)
class MotionObservation:
    """Single motion assessment observation from the risk engine."""
    timestamp: datetime
    level: MotionLevel
    peak_vibration_mg: Optional[float] = None
    vibration_over_threshold: int = 0
    tilt_change_deg: Optional[float] = None


@dataclass(frozen=True)
class StateTransition:
    """Result of a state machine transition."""
    previous_state: SeismicState
    new_state: SeismicState
    event_started: bool = False
    event_ended: bool = False
    recovery_started: bool = False
    recovery_completed: bool = False
    gap_entered: bool = False
    gap_resumed: bool = False
    abnormal_during_gap: bool = False
    normal_during_gap: bool = False


@dataclass
class SeismicDeviceEvent:
    """Tracks a single device's seismic event lifecycle (in-memory)."""
    state: SeismicState = SeismicState.QUIET
    event_started_at: Optional[datetime] = None
    event_ended_at: Optional[datetime] = None
    peak_vibration_mg: Optional[float] = None
    last_observation_at: Optional[datetime] = None
    recovery_window_count: int = 0
    recovery_started_at: Optional[datetime] = None
    gap_entered_at: Optional[datetime] = None

    def is_event_active(self) -> bool:
        return self.state in (SeismicState.ACTIVE, SeismicState.RECOVERY, SeismicState.TELEMETRY_GAP)

    def current_event_duration(self, now: datetime) -> Optional[timedelta]:
        if self.event_started_at is None:
            return None
        end = self.event_ended_at or now
        return end - self.event_started_at


class SeismicStateMachine:
    """Pure deterministic state machine for one seismic device."""

    def __init__(
        self,
        recovery_windows: int = 3,
        gap_tolerance_seconds: int = 300,
    ):
        if recovery_windows < 1:
            raise ValueError("recovery_windows must be >= 1")
        if gap_tolerance_seconds < 0:
            raise ValueError("gap_tolerance_seconds must be >= 0")

        self._recovery_windows = recovery_windows
        self._gap_tolerance = timedelta(seconds=gap_tolerance_seconds)
        self._device_event = SeismicDeviceEvent()

    @property
    def state(self) -> SeismicState:
        return self._device_event.state

    @property
    def device_event(self) -> SeismicDeviceEvent:
        return self._device_event

    @property
    def recovery_windows_required(self) -> int:
        return self._recovery_windows

    @property
    def gap_tolerance(self) -> timedelta:
        return self._gap_tolerance

    def _make_transition(
        self,
        new_state: SeismicState,
        **signals
    ) -> StateTransition:
        previous = self._device_event.state
        self._device_event.state = new_state
        return StateTransition(previous_state=previous, new_state=new_state, **signals)

    def _update_peak(self, observation: MotionObservation) -> None:
        if observation.peak_vibration_mg is not None and observation.level == MotionLevel.ELEVATED:
            current = self._device_event.peak_vibration_mg
            if current is None or observation.peak_vibration_mg > current:
                self._device_event.peak_vibration_mg = observation.peak_vibration_mg

    def process_observation(self, observation: MotionObservation) -> StateTransition:
        """Process a motion observation and return the transition."""
        if self._device_event.last_observation_at is not None:
            if observation.timestamp < self._device_event.last_observation_at:
                raise ValueError(
                    f"Observation timestamp {observation.timestamp} is before "
                    f"last accepted observation {self._device_event.last_observation_at}"
                )

        self._device_event.last_observation_at = observation.timestamp

        if self._device_event.state == SeismicState.QUIET:
            return self._process_quiet(observation)
        elif self._device_event.state == SeismicState.ACTIVE:
            return self._process_active(observation)
        elif self._device_event.state == SeismicState.RECOVERY:
            return self._process_recovery(observation)
        elif self._device_event.state == SeismicState.TELEMETRY_GAP:
            return self._process_gap(observation)
        else:
            raise ValueError(f"Unknown state: {self._device_event.state}")

    def _process_quiet(self, observation: MotionObservation) -> StateTransition:
        if observation.level == MotionLevel.ELEVATED:
            self._device_event.event_started_at = observation.timestamp
            self._device_event.peak_vibration_mg = None
            self._update_peak(observation)
            return self._make_transition(SeismicState.ACTIVE, event_started=True)
        return self._make_transition(SeismicState.QUIET)

    def _process_active(self, observation: MotionObservation) -> StateTransition:
        self._update_peak(observation)

        if observation.level == MotionLevel.ELEVATED:
            return self._make_transition(SeismicState.ACTIVE)

        if observation.level == MotionLevel.NORMAL:
            self._device_event.recovery_window_count = 1
            self._device_event.recovery_started_at = observation.timestamp
            return self._make_transition(SeismicState.RECOVERY, recovery_started=True)

        if observation.level == MotionLevel.UNCHARACTERIZED:
            return self._make_transition(SeismicState.ACTIVE)

        return self._make_transition(SeismicState.ACTIVE)

    def _process_recovery(self, observation: MotionObservation) -> StateTransition:
        if observation.level == MotionLevel.ELEVATED:
            self._device_event.recovery_window_count = 0
            self._device_event.recovery_started_at = None
            self._update_peak(observation)
            return self._make_transition(SeismicState.ACTIVE)

        if observation.level == MotionLevel.NORMAL:
            self._device_event.recovery_window_count += 1
            if self._device_event.recovery_window_count >= self._recovery_windows:
                self._device_event.event_ended_at = observation.timestamp
                return self._make_transition(
                    SeismicState.QUIET,
                    event_ended=True,
                    recovery_completed=True
                )
            return self._make_transition(SeismicState.RECOVERY)

        return self._make_transition(SeismicState.RECOVERY)

    def _process_gap(self, observation: MotionObservation) -> StateTransition:
        if observation.level == MotionLevel.ELEVATED:
            return self._make_transition(
                SeismicState.ACTIVE,
                gap_resumed=True,
                abnormal_during_gap=True
            )
        if observation.level == MotionLevel.NORMAL:
            self._device_event.recovery_window_count = 1
            self._device_event.recovery_started_at = observation.timestamp
            return self._make_transition(
                SeismicState.RECOVERY,
                gap_resumed=True,
                normal_during_gap=True,
                recovery_started=True
            )
        return self._make_transition(SeismicState.TELEMETRY_GAP, gap_resumed=True)

    def check_gap(self, current_time: datetime) -> Optional[StateTransition]:
        """Check if telemetry gap has been exceeded. Call periodically or before new observations."""
        last_obs = self._device_event.last_observation_at
        if last_obs is None:
            return None

        if self._device_event.state in (SeismicState.ACTIVE, SeismicState.RECOVERY):
            gap = current_time - last_obs
            if gap >= self._gap_tolerance:
                self._device_event.gap_entered_at = current_time
                return self._make_transition(SeismicState.TELEMETRY_GAP, gap_entered=True)
        return None

    def get_status_summary(self) -> dict:
        """Return a summary of current state for debugging/logging."""
        return {
            "state": self._device_event.state.value,
            "event_active": self._device_event.is_event_active(),
            "event_started_at": self._device_event.event_started_at.isoformat() if self._device_event.event_started_at else None,
            "event_ended_at": self._device_event.event_ended_at.isoformat() if self._device_event.event_ended_at else None,
            "peak_vibration_mg": self._device_event.peak_vibration_mg,
            "last_observation_at": self._device_event.last_observation_at.isoformat() if self._device_event.last_observation_at else None,
            "recovery_window_count": self._device_event.recovery_window_count,
            "recovery_windows_required": self._recovery_windows,
        }


def motion_level_from_risk_assessment(assessment) -> MotionLevel:
    """Convert a risk_engine.RiskAssessment level to MotionLevel."""
    level_map = {
        "elevated_motion": MotionLevel.ELEVATED,
        "normal_motion": MotionLevel.NORMAL,
        "uncharacterized": MotionLevel.UNCHARACTERIZED,
    }
    return level_map.get(assessment.level, MotionLevel.UNCHARACTERIZED)


def create_motion_observation(
    timestamp: datetime,
    assessment,
    peak_vibration_mg: Optional[float] = None,
    vibration_over_threshold: int = 0,
    tilt_change_deg: Optional[float] = None,
) -> MotionObservation:
    """Create a MotionObservation from a risk_engine.RiskAssessment."""
    return MotionObservation(
        timestamp=timestamp,
        level=motion_level_from_risk_assessment(assessment),
        peak_vibration_mg=peak_vibration_mg or assessment.evidence.get("max_vibration_mg"),
        vibration_over_threshold=vibration_over_threshold or assessment.evidence.get("vibration_over_threshold", 0),
        tilt_change_deg=tilt_change_deg or assessment.evidence.get("tilt_change_deg"),
    )