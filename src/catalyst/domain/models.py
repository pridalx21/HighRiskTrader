"""Validated immutable models used by replay and demo execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from re import fullmatch

from catalyst.domain.enums import (
    AccountMode,
    Direction,
    EventImportance,
    EventStatus,
    ReasonCode,
    SystemState,
)

ZERO = Decimal("0")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def _require_finite_positive(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValueError(f"{field_name} must be Decimal")
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field_name} must be finite and positive")


def _require_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValueError(f"{field_name} must be Decimal")


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event_id: str
    name: str
    scheduled_at: datetime
    ingested_at: datetime
    currency: str
    importance: EventImportance
    status: EventStatus
    eligible_symbols: tuple[str, ...]
    source: str = "manual"

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        if self.currency.upper() in {"UNKNOWN", "N/A"}:
            raise ValueError("currency must be known")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if not self.eligible_symbols or any(not symbol.strip() for symbol in self.eligible_symbols):
            raise ValueError("eligible_symbols must contain non-empty symbols")
        if len(set(self.eligible_symbols)) != len(self.eligible_symbols):
            raise ValueError("eligible_symbols must not contain duplicates")
        _require_utc(self.scheduled_at, "scheduled_at")
        _require_utc(self.ingested_at, "ingested_at")


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    pre_event_high: Decimal
    pre_event_low: Decimal
    atr: Decimal
    baseline_spread: Decimal
    data_age_seconds: Decimal
    retest_holds: bool
    stop_candidate: Decimal
    related_markets_observed: int
    cross_asset_confirmations: int
    market_open: bool

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        _require_utc(self.timestamp, "timestamp")
        for field_name in (
            "bid",
            "ask",
            "pre_event_high",
            "pre_event_low",
            "atr",
            "baseline_spread",
            "stop_candidate",
        ):
            _require_finite_positive(getattr(self, field_name), field_name)
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        if self.pre_event_high <= self.pre_event_low:
            raise ValueError("pre_event_high must be greater than pre_event_low")
        _require_decimal(self.data_age_seconds, "data_age_seconds")
        if not self.data_age_seconds.is_finite() or self.data_age_seconds < ZERO:
            raise ValueError("data_age_seconds must be finite and non-negative")
        if self.related_markets_observed < 0 or self.cross_asset_confirmations < 0:
            raise ValueError("confirmation counts must be non-negative")
        if self.cross_asset_confirmations > self.related_markets_observed:
            raise ValueError("confirmations cannot exceed observed related markets")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_multiple(self) -> Decimal:
        return self.spread / self.baseline_spread


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    mode: AccountMode
    currency: str
    balance: Decimal
    equity: Decimal
    day_start_equity: Decimal
    month_start_equity: Decimal
    daily_realized_pnl: Decimal
    consecutive_losses: int
    active_risk_clusters: int
    open_worst_case_risk: Decimal
    timestamp: datetime
    connected: bool = True

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        if self.currency.upper() in {"UNKNOWN", "N/A"}:
            raise ValueError("currency must be known")
        for field_name in ("balance", "equity", "day_start_equity", "month_start_equity"):
            _require_finite_positive(getattr(self, field_name), field_name)
        _require_decimal(self.daily_realized_pnl, "daily_realized_pnl")
        if not self.daily_realized_pnl.is_finite():
            raise ValueError("daily_realized_pnl must be finite")
        _require_decimal(self.open_worst_case_risk, "open_worst_case_risk")
        if not self.open_worst_case_risk.is_finite() or self.open_worst_case_risk < ZERO:
            raise ValueError("open_worst_case_risk must be finite and non-negative")
        if self.consecutive_losses < 0 or self.active_risk_clusters < 0:
            raise ValueError("loss and cluster counts must be non-negative")
        _require_utc(self.timestamp, "timestamp")


@dataclass(frozen=True, slots=True)
class BrokerContract:
    """Broker economics; commission is total round-trip cost per volume."""

    symbol: str
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    profit_currency: str
    account_currency: str
    profit_to_account_rate: Decimal
    volume_minimum: Decimal
    volume_maximum: Decimal
    volume_step: Decimal
    commission_per_volume: Decimal
    slippage_ticks: Decimal

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("contract symbol must not be empty")
        if not self.profit_currency.strip() or not self.account_currency.strip():
            raise ValueError("contract currencies must not be empty")
        if self.profit_currency.upper() in {"UNKNOWN", "N/A"}:
            raise ValueError("profit_currency must be known")
        if self.account_currency.upper() in {"UNKNOWN", "N/A"}:
            raise ValueError("account_currency must be known")
        for field_name in (
            "tick_size",
            "tick_value",
            "contract_size",
            "profit_to_account_rate",
            "volume_minimum",
            "volume_maximum",
            "volume_step",
        ):
            _require_finite_positive(getattr(self, field_name), field_name)
        for field_name in ("commission_per_volume", "slippage_ticks"):
            value = getattr(self, field_name)
            _require_decimal(value, field_name)
            if not value.is_finite() or value < ZERO:
                raise ValueError(f"{field_name} must be finite and non-negative")
        if self.commission_per_volume == ZERO and self.slippage_ticks == ZERO:
            raise ValueError("a pessimistic commission or slippage allowance is required")
        if self.volume_minimum > self.volume_maximum:
            raise ValueError("volume_minimum must not exceed volume_maximum")
        if self.volume_minimum % self.volume_step != ZERO:
            raise ValueError("volume_minimum must align to volume_step")
        if self.volume_maximum % self.volume_step != ZERO:
            raise ValueError("volume_maximum must align to volume_step")
        same_currency = self.profit_currency.upper() == self.account_currency.upper()
        if same_currency and self.profit_to_account_rate != Decimal("1"):
            raise ValueError("same-currency conversion rate must equal 1")


@dataclass(frozen=True, slots=True)
class GateResult:
    code: ReasonCode
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("gate reason must not be empty")


@dataclass(frozen=True, slots=True)
class StateResult:
    state: SystemState
    code: ReasonCode
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("state reason must not be empty")


@dataclass(frozen=True, slots=True)
class SetupEvaluation:
    catalyst: GateResult
    acceptance: GateResult
    confirmation: GateResult
    execution: GateResult
    direction: Direction | None

    @property
    def all_green(self) -> bool:
        return all(
            gate.passed
            for gate in (self.catalyst, self.acceptance, self.confirmation, self.execution)
        )

    @property
    def failed_reasons(self) -> tuple[str, ...]:
        return tuple(
            gate.reason
            for gate in (self.catalyst, self.acceptance, self.confirmation, self.execution)
            if not gate.passed
        )


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    code: ReasonCode
    reason: str
    risk_amount: Decimal = ZERO

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("risk reason must not be empty")
        _require_decimal(self.risk_amount, "risk_amount")
        if not self.risk_amount.is_finite() or self.risk_amount < ZERO:
            raise ValueError("risk_amount must be finite and non-negative")
        if not self.allowed and self.risk_amount != ZERO:
            raise ValueError("rejected risk decisions must have zero risk_amount")


@dataclass(frozen=True, slots=True)
class PositionSize:
    quantity: Decimal
    maximum_loss: Decimal

    def __post_init__(self) -> None:
        _require_finite_positive(self.quantity, "quantity")
        _require_finite_positive(self.maximum_loss, "maximum_loss")


@dataclass(frozen=True, slots=True)
class TradePlan:
    decision_id: str
    event_id: str
    strategy_id: str
    symbol: str
    direction: Direction
    created_at: datetime
    entry: Decimal
    stop: Decimal
    risk_amount: Decimal
    maximum_loss: Decimal
    quantity: Decimal
    configuration_hash: str
    rationale: tuple[str, ...]
    server_side_stop_required: bool = True

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.decision_id, self.event_id, self.strategy_id, self.symbol)
        ):
            raise ValueError("trade identifiers must not be empty")
        _require_utc(self.created_at, "created_at")
        for field_name in ("entry", "stop", "risk_amount", "maximum_loss", "quantity"):
            _require_finite_positive(getattr(self, field_name), field_name)
        if self.maximum_loss > self.risk_amount:
            raise ValueError("maximum_loss must not exceed risk_amount")
        if self.direction is Direction.LONG and self.stop >= self.entry:
            raise ValueError("long stop must be below entry")
        if self.direction is Direction.SHORT and self.stop <= self.entry:
            raise ValueError("short stop must be above entry")
        if not self.server_side_stop_required:
            raise ValueError("protective broker-side stop is mandatory")
        if fullmatch(r"[0-9a-f]{64}", self.configuration_hash) is None:
            raise ValueError("configuration_hash must be a lowercase SHA-256 digest")
        if not self.rationale or any(not reason.strip() for reason in self.rationale):
            raise ValueError("trade rationale must contain non-empty reasons")


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    state: SystemState
    code: ReasonCode
    setup: SetupEvaluation
    risk: RiskDecision
    plan: TradePlan | None
    reason: str
    configuration_hash: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("pipeline decision reason must not be empty")
        if fullmatch(r"[0-9a-f]{64}", self.configuration_hash) is None:
            raise ValueError("configuration_hash must be a lowercase SHA-256 digest")
        if self.plan is not None and (not self.setup.all_green or not self.risk.allowed):
            raise ValueError("trade plan requires green setup and allowed risk")
