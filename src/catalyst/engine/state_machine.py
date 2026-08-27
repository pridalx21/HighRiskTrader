"""Pure event lifecycle state machine."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from catalyst.domain.enums import ReasonCode, SystemState
from catalyst.domain.models import EconomicEvent, SetupEvaluation, StateResult


@dataclass(frozen=True, slots=True)
class StateMachineConfig:
    pre_arm: timedelta = timedelta(minutes=30)
    shock_window: timedelta = timedelta(seconds=90)
    entry_deadline: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.pre_arm <= timedelta(0):
            raise ValueError("pre_arm must be positive")
        if self.shock_window < timedelta(0):
            raise ValueError("shock_window must be non-negative")
        if self.entry_deadline <= self.shock_window:
            raise ValueError("entry_deadline must follow shock_window")


class EventStateMachine:
    def __init__(self, config: StateMachineConfig | None = None) -> None:
        self.config = config or StateMachineConfig()

    def state_for(
        self,
        now: datetime,
        event: EconomicEvent,
        setup: SetupEvaluation,
        *,
        auto_demo_armed: bool = True,
        risk_locked: bool = False,
        has_position: bool = False,
    ) -> StateResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware UTC")
        if now.utcoffset() != timedelta(0):
            raise ValueError("now must be normalized to UTC")
        if not auto_demo_armed:
            return StateResult(
                SystemState.DISARMED,
                ReasonCode.STATE_DISARMED,
                "automatic demo execution is disarmed",
            )
        if risk_locked:
            return StateResult(
                SystemState.LOCKED,
                ReasonCode.STATE_RISK_LOCKED,
                "a risk lock is active",
            )
        if has_position:
            return StateResult(
                SystemState.IN_POSITION,
                ReasonCode.STATE_IN_POSITION,
                "a managed position is active",
            )

        arm_at = event.scheduled_at - self.config.pre_arm
        shock_ends = event.scheduled_at + self.config.shock_window
        expires_at = event.scheduled_at + self.config.entry_deadline
        if now < arm_at:
            return StateResult(
                SystemState.SLEEPING,
                ReasonCode.STATE_SLEEPING,
                "event is outside the pre-arm window",
            )
        if now < event.scheduled_at:
            return StateResult(
                SystemState.ARMED,
                ReasonCode.STATE_ARMED,
                "event is inside the pre-arm window",
            )
        if now < shock_ends:
            return StateResult(
                SystemState.SHOCK_WINDOW,
                ReasonCode.STATE_SHOCK_WINDOW,
                "post-release shock window is active",
            )
        if now > expires_at:
            return StateResult(
                SystemState.EXPIRED,
                ReasonCode.STATE_EXPIRED,
                "event entry window has expired",
            )
        if setup.all_green:
            return StateResult(
                SystemState.READY,
                ReasonCode.STATE_READY,
                "all setup gates are green",
            )
        return StateResult(
            SystemState.WAITING_RETEST,
            ReasonCode.STATE_WAITING_RETEST,
            "one or more setup gates are red",
        )
