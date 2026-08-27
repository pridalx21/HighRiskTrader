"""Pure fail-closed intraday exit engine shared by replay and demo adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from catalyst.domain.enums import Direction

ZERO = Decimal("0")


def _utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def _positive(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field_name} must be a finite positive Decimal")


class ExitReason(StrEnum):
    NONE = "none"
    EMERGENCY = "emergency"
    PROTECTIVE_STOP = "protective_stop"
    RANGE_RECLAIM = "range_reclaim"
    SESSION_CUTOFF = "session_cutoff"


@dataclass(frozen=True, slots=True)
class ExitQuote:
    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("quote symbol must not be empty")
        _utc(self.timestamp, "quote timestamp")
        _positive(self.bid, "quote bid")
        _positive(self.ask, "quote ask")
        if self.ask < self.bid:
            raise ValueError("quote ask must not be below bid")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    symbol: str
    direction: Direction
    entry: Decimal
    initial_stop: Decimal
    current_stop: Decimal
    quantity: Decimal
    opened_at: datetime
    pre_event_high: Decimal
    pre_event_low: Decimal
    session_cutoff: datetime

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("position symbol must not be empty")
        for field_name in (
            "entry",
            "initial_stop",
            "current_stop",
            "quantity",
            "pre_event_high",
            "pre_event_low",
        ):
            _positive(getattr(self, field_name), field_name)
        _utc(self.opened_at, "opened_at")
        _utc(self.session_cutoff, "session_cutoff")
        if self.session_cutoff <= self.opened_at:
            raise ValueError("session cutoff must follow position opening")
        if self.pre_event_high <= self.pre_event_low:
            raise ValueError("position pre-event range is invalid")
        if self.direction is Direction.LONG:
            if self.initial_stop >= self.entry or self.current_stop >= self.entry:
                raise ValueError("long stops must remain below entry")
            if self.current_stop < self.initial_stop:
                raise ValueError("long stop must never be widened")
        else:
            if self.initial_stop <= self.entry or self.current_stop <= self.entry:
                raise ValueError("short stops must remain above entry")
            if self.current_stop > self.initial_stop:
                raise ValueError("short stop must never be widened")


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool
    reason: ExitReason
    code: str
    detail: str
    timestamp: datetime
    exit_price: Decimal | None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.detail.strip():
            raise ValueError("exit code and detail must not be empty")
        _utc(self.timestamp, "exit timestamp")
        if self.should_exit != (self.exit_price is not None):
            raise ValueError("exit flag and executable price must agree")
        if self.exit_price is not None:
            _positive(self.exit_price, "exit_price")


class IntradayExitEngine:
    """Evaluate emergency, hard stop, range reclaim, then UTC cutoff."""

    def evaluate(
        self,
        position: ManagedPosition,
        quote: ExitQuote,
        now: datetime,
        *,
        maximum_data_age_seconds: Decimal,
        emergency: bool = False,
    ) -> ExitDecision:
        _utc(now, "now")
        if quote.symbol != position.symbol:
            raise ValueError("exit quote symbol does not match position")
        if not isinstance(maximum_data_age_seconds, Decimal):
            raise ValueError("maximum_data_age_seconds must be Decimal")
        age = now - quote.timestamp
        age_seconds = Decimal(age.days * 86_400 + age.seconds)
        age_seconds += Decimal(age.microseconds) / Decimal("1000000")
        if age_seconds < ZERO or age_seconds > maximum_data_age_seconds:
            raise ValueError("exit quote is future-dated or stale")

        price = quote.bid if position.direction is Direction.LONG else quote.ask
        if emergency:
            return self._exit(ExitReason.EMERGENCY, "EMERGENCY_EXIT", now, price)
        stop_hit = (
            price <= position.current_stop
            if position.direction is Direction.LONG
            else price >= position.current_stop
        )
        if stop_hit:
            return self._exit(
                ExitReason.PROTECTIVE_STOP,
                "PROTECTIVE_STOP_HIT",
                now,
                price,
            )
        if position.pre_event_low <= quote.mid <= position.pre_event_high:
            return self._exit(
                ExitReason.RANGE_RECLAIM,
                "PRE_EVENT_RANGE_RECLAIMED",
                now,
                price,
            )
        if now >= position.session_cutoff:
            return self._exit(
                ExitReason.SESSION_CUTOFF,
                "SESSION_CUTOFF",
                now,
                price,
            )
        return ExitDecision(
            should_exit=False,
            reason=ExitReason.NONE,
            code="HOLD_POSITION",
            detail="no configured intraday exit condition is active",
            timestamp=now,
            exit_price=None,
        )

    @staticmethod
    def _exit(
        reason: ExitReason,
        code: str,
        timestamp: datetime,
        price: Decimal,
    ) -> ExitDecision:
        return ExitDecision(
            should_exit=True,
            reason=reason,
            code=code,
            detail=f"position exits because {reason.value} is active",
            timestamp=timestamp,
            exit_price=price,
        )
