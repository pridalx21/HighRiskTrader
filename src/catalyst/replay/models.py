"""Immutable contracts for raw replay inputs and execution evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from catalyst.domain.enums import Direction
from catalyst.domain.models import AccountSnapshot, BrokerContract, EconomicEvent

ZERO = Decimal("0")
ONE = Decimal("1")


def require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def require_decimal(value: Decimal, field_name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise ValueError(f"{field_name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if positive and value <= ZERO:
        raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, slots=True)
class RawTick:
    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    source_sequence: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("tick symbol must not be empty")
        require_utc(self.timestamp, "tick timestamp")
        require_decimal(self.bid, "tick bid", positive=True)
        require_decimal(self.ask, "tick ask", positive=True)
        if self.ask < self.bid:
            raise ValueError("tick ask must be greater than or equal to bid")
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise ValueError("tick source_sequence must be a non-negative integer")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class RawBar:
    symbol: str
    opened_at: datetime
    closed_at: datetime
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal
    source_sequence: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("bar symbol must not be empty")
        require_utc(self.opened_at, "bar opened_at")
        require_utc(self.closed_at, "bar closed_at")
        if self.closed_at <= self.opened_at:
            raise ValueError("bar closed_at must follow opened_at")
        for field_name in (
            "bid_open",
            "bid_high",
            "bid_low",
            "bid_close",
            "ask_open",
            "ask_high",
            "ask_low",
            "ask_close",
        ):
            require_decimal(getattr(self, field_name), field_name, positive=True)
        if self.bid_low > min(self.bid_open, self.bid_close, self.bid_high):
            raise ValueError("bid_low is inconsistent with bid OHLC")
        if self.bid_high < max(self.bid_open, self.bid_close, self.bid_low):
            raise ValueError("bid_high is inconsistent with bid OHLC")
        if self.ask_low > min(self.ask_open, self.ask_close, self.ask_high):
            raise ValueError("ask_low is inconsistent with ask OHLC")
        if self.ask_high < max(self.ask_open, self.ask_close, self.ask_low):
            raise ValueError("ask_high is inconsistent with ask OHLC")
        if any(
            ask < bid
            for bid, ask in (
                (self.bid_open, self.ask_open),
                (self.bid_high, self.ask_high),
                (self.bid_low, self.ask_low),
                (self.bid_close, self.ask_close),
            )
        ):
            raise ValueError("bar ask values must not be below bid values")
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise ValueError("bar source_sequence must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CrossAssetRule:
    symbol: str
    polarity: int
    minimum_move: Decimal

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("cross-asset symbol must not be empty")
        if self.polarity not in (-1, 1):
            raise ValueError("cross-asset polarity must be -1 or 1")
        require_decimal(self.minimum_move, "minimum_move", positive=True)


@dataclass(frozen=True, slots=True)
class CrossAssetVote:
    symbol: str
    direction: Direction | None
    observed_at: datetime
    signed_move: Decimal

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("vote symbol must not be empty")
        require_utc(self.observed_at, "vote observed_at")
        require_decimal(self.signed_move, "signed_move")


class FeatureStatus(StrEnum):
    READY = "ready"
    NO_BREAKOUT = "no_breakout"
    NO_RETEST = "no_retest"
    RANGE_RECLAIMED = "range_reclaimed"
    WHIPSAW = "whipsaw"
    INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass(frozen=True, slots=True)
class FeatureEvidence:
    status: FeatureStatus
    pre_event_high: Decimal
    pre_event_low: Decimal
    baseline_spread: Decimal
    atr: Decimal
    breakout_direction: Direction | None
    breakout_at: datetime | None
    retest_at: datetime | None
    hold_at: datetime | None
    votes: tuple[CrossAssetVote, ...]
    reason: str

    def __post_init__(self) -> None:
        for field_name in ("pre_event_high", "pre_event_low", "baseline_spread", "atr"):
            require_decimal(getattr(self, field_name), field_name, positive=True)
        if self.pre_event_high <= self.pre_event_low:
            raise ValueError("feature pre-event range is invalid")
        for field_name in ("breakout_at", "retest_at", "hold_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name)
        if not self.reason.strip():
            raise ValueError("feature reason must not be empty")


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    latency_milliseconds: int
    maximum_adverse_slippage_ticks: Decimal
    fill_fraction: Decimal = ONE
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.latency_milliseconds) is not int or self.latency_milliseconds < 0:
            raise ValueError("latency_milliseconds must be a non-negative integer")
        require_decimal(
            self.maximum_adverse_slippage_ticks,
            "maximum_adverse_slippage_ticks",
        )
        if self.maximum_adverse_slippage_ticks < ZERO:
            raise ValueError("maximum_adverse_slippage_ticks must be non-negative")
        require_decimal(self.fill_fraction, "fill_fraction", positive=True)
        if self.fill_fraction > ONE:
            raise ValueError("fill_fraction must not exceed 1")
        if self.rejection_code is not None and not self.rejection_code.strip():
            raise ValueError("rejection_code must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    scenario_id: str
    event: EconomicEvent
    primary_symbol: str
    ticks: tuple[RawTick, ...]
    bars: tuple[RawBar, ...]
    related_rules: tuple[CrossAssetRule, ...]
    account: AccountSnapshot
    contract: BrokerContract
    execution: ExecutionScenario
    evaluation_delay_seconds: Decimal
    session_cutoff: datetime
    market_open: bool = True
    emergency_exit: bool = False

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or not self.primary_symbol.strip():
            raise ValueError("scenario and primary symbol must not be empty")
        if self.primary_symbol not in self.event.eligible_symbols:
            raise ValueError("primary symbol must be eligible for the event")
        if self.contract.symbol != self.primary_symbol:
            raise ValueError("contract symbol must match primary symbol")
        if self.execution.maximum_adverse_slippage_ticks > self.contract.slippage_ticks:
            raise ValueError("execution slippage limit must not exceed sized contract allowance")
        if not self.ticks or not any(tick.symbol == self.primary_symbol for tick in self.ticks):
            raise ValueError("scenario requires primary-symbol ticks")
        if not self.bars or not any(bar.symbol == self.primary_symbol for bar in self.bars):
            raise ValueError("scenario requires primary-symbol bars")
        tick_keys = {(tick.timestamp, tick.symbol, tick.source_sequence) for tick in self.ticks}
        if len(tick_keys) != len(self.ticks):
            raise ValueError("scenario tick identities must be unique")
        bar_keys = {(bar.opened_at, bar.symbol, bar.source_sequence) for bar in self.bars}
        if len(bar_keys) != len(self.bars):
            raise ValueError("scenario bar identities must be unique")
        rule_symbols = tuple(rule.symbol for rule in self.related_rules)
        if len(set(rule_symbols)) != len(rule_symbols):
            raise ValueError("related rule symbols must be unique")
        require_decimal(self.evaluation_delay_seconds, "evaluation_delay_seconds")
        if self.evaluation_delay_seconds < ZERO:
            raise ValueError("evaluation_delay_seconds must be non-negative")
        microseconds = self.evaluation_delay_seconds * Decimal("1000000")
        if microseconds != microseconds.to_integral_value():
            raise ValueError("evaluation_delay_seconds supports at most six decimals")
        require_utc(self.session_cutoff, "session_cutoff")
        if self.session_cutoff <= self.event.scheduled_at:
            raise ValueError("session_cutoff must follow the event")


class ExecutionStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"
    MISSED = "missed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    code: str
    reason: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    intended_entry: Decimal
    fill_price: Decimal | None
    fill_timestamp: datetime | None
    observed_spread: Decimal | None
    adverse_slippage_ticks: Decimal | None
    commission: Decimal

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.reason.strip():
            raise ValueError("execution code and reason must not be empty")
        for field_name in ("requested_quantity", "intended_entry"):
            require_decimal(getattr(self, field_name), field_name, positive=True)
        for field_name in ("filled_quantity", "commission"):
            value = getattr(self, field_name)
            require_decimal(value, field_name)
            if value < ZERO:
                raise ValueError(f"{field_name} must be non-negative")
        for field_name in ("fill_price", "observed_spread", "adverse_slippage_ticks"):
            value = getattr(self, field_name)
            if value is not None:
                require_decimal(value, field_name)
                if value < ZERO:
                    raise ValueError(f"{field_name} must be non-negative")
        if self.fill_timestamp is not None:
            require_utc(self.fill_timestamp, "fill_timestamp")
        filled = self.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIAL)
        if filled and (self.fill_price is None or self.fill_timestamp is None):
            raise ValueError("filled execution requires price and timestamp")
        if not filled and self.filled_quantity != ZERO:
            raise ValueError("unfilled execution must have zero filled_quantity")


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    decision_code: str
    direction: Direction | None
    execution_status: ExecutionStatus | None
    exit_reason: str | None

    def __post_init__(self) -> None:
        if not self.decision_code.strip():
            raise ValueError("expected decision_code must not be empty")
        if self.exit_reason is not None and not self.exit_reason.strip():
            raise ValueError("expected exit_reason must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class ReplayFixture:
    scenario: ReplayScenario
    expected: ExpectedOutcome
