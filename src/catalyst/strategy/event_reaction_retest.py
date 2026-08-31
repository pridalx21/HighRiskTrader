"""Deterministic four-gate Event Reaction Retest hypothesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from catalyst.domain.enums import Direction, EventImportance, EventStatus, ReasonCode
from catalyst.domain.models import EconomicEvent, GateResult, MarketSnapshot, SetupEvaluation


@dataclass(frozen=True, slots=True)
class EventReactionRetestConfig:
    strategy_id: str = "event_reaction_retest_v1"
    shock_window_seconds: int = 90
    entry_deadline_seconds: int = 900
    minimum_related_markets: int = 2
    minimum_confirmations: int = 2
    maximum_spread_multiple: Decimal = Decimal("2.5")
    maximum_data_age_seconds: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if self.shock_window_seconds < 0:
            raise ValueError("shock_window_seconds must be non-negative")
        if self.entry_deadline_seconds <= self.shock_window_seconds:
            raise ValueError("entry deadline must be after shock window")
        if self.minimum_related_markets < 1 or self.minimum_confirmations < 1:
            raise ValueError("confirmation minimums must be positive")
        if self.minimum_confirmations > self.minimum_related_markets:
            raise ValueError("minimum confirmations cannot exceed minimum observed markets")
        if not isinstance(self.maximum_spread_multiple, Decimal):
            raise ValueError("maximum_spread_multiple must be Decimal")
        if not isinstance(self.maximum_data_age_seconds, Decimal):
            raise ValueError("maximum_data_age_seconds must be Decimal")
        if (
            not self.maximum_spread_multiple.is_finite()
            or not self.maximum_data_age_seconds.is_finite()
            or self.maximum_spread_multiple <= 0
            or self.maximum_data_age_seconds < 0
        ):
            raise ValueError("execution limits are invalid")


class EventReactionRetestStrategy:
    def __init__(self, config: EventReactionRetestConfig | None = None) -> None:
        self.config = config or EventReactionRetestConfig()

    def evaluate(
        self,
        event: EconomicEvent,
        market: MarketSnapshot,
        now: datetime,
    ) -> SetupEvaluation:
        utc_offset = now.utcoffset()
        if now.tzinfo is None or utc_offset is None:
            raise ValueError("now must be timezone-aware UTC")
        if utc_offset.total_seconds() != 0:
            raise ValueError("now must be normalized to UTC")

        seconds_since_event = (now - event.scheduled_at).total_seconds()
        catalyst_passed = (
            event.importance is EventImportance.HIGH
            and event.status is EventStatus.SCHEDULED
            and market.symbol in event.eligible_symbols
            and self.config.shock_window_seconds
            <= seconds_since_event
            <= self.config.entry_deadline_seconds
        )
        if event.importance is not EventImportance.HIGH:
            catalyst_code = ReasonCode.EVENT_NOT_HIGH_IMPORTANCE
            catalyst_reason = "event is not high importance"
        elif event.status is not EventStatus.SCHEDULED:
            catalyst_code = ReasonCode.EVENT_NOT_ELIGIBLE
            catalyst_reason = f"event status is {event.status.value}"
        elif market.symbol not in event.eligible_symbols:
            catalyst_code = ReasonCode.SYMBOL_NOT_MAPPED
            catalyst_reason = "logical symbol is not mapped to the event"
        elif seconds_since_event < self.config.shock_window_seconds:
            catalyst_code = ReasonCode.SHOCK_WINDOW_ACTIVE
            catalyst_reason = "post-release shock window is active"
        elif seconds_since_event > self.config.entry_deadline_seconds:
            catalyst_code = ReasonCode.ENTRY_WINDOW_EXPIRED
            catalyst_reason = "event entry window has expired"
        else:
            catalyst_code = ReasonCode.CATALYST_PASS
            catalyst_reason = "eligible event is inside the entry window"

        direction: Direction | None
        if market.mid > market.pre_event_high:
            direction = Direction.LONG
        elif market.mid < market.pre_event_low:
            direction = Direction.SHORT
        else:
            direction = None

        acceptance_passed = direction is not None and market.retest_holds
        if direction is None:
            acceptance_code = ReasonCode.PRICE_INSIDE_RANGE
            acceptance_reason = "price has not accepted outside the pre-event range"
        elif not market.retest_holds:
            acceptance_code = ReasonCode.RETEST_INVALID
            acceptance_reason = "candidate breakout has no valid held retest"
        else:
            acceptance_code = ReasonCode.ACCEPTANCE_PASS
            acceptance_reason = f"{direction.value} breakout retest holds"

        confirmation_passed = (
            market.related_markets_observed >= self.config.minimum_related_markets
            and market.cross_asset_confirmations >= self.config.minimum_confirmations
        )
        if market.related_markets_observed < self.config.minimum_related_markets:
            confirmation_code = ReasonCode.RELATED_MARKETS_MISSING
            confirmation_reason = "too few related markets are available"
        elif market.cross_asset_confirmations < self.config.minimum_confirmations:
            confirmation_code = ReasonCode.CONFIRMATION_INSUFFICIENT
            confirmation_reason = "cross-asset confirmation threshold is not met"
        else:
            confirmation_code = ReasonCode.CONFIRMATION_PASS
            confirmation_reason = "cross-asset confirmation threshold is met"

        spread_ok = market.spread_multiple <= self.config.maximum_spread_multiple
        age_delta = now - market.timestamp
        observed_age = Decimal(age_delta.days * 86_400 + age_delta.seconds)
        observed_age += Decimal(age_delta.microseconds) / Decimal("1000000")
        freshness_ok = (
            observed_age >= 0
            and observed_age == market.data_age_seconds
            and observed_age <= self.config.maximum_data_age_seconds
        )
        stop_ok = self._stop_is_valid(direction, market)
        execution_passed = market.market_open and spread_ok and freshness_ok and stop_ok
        if not market.market_open:
            execution_code = ReasonCode.MARKET_CLOSED
            execution_reason = "market is closed"
        elif not spread_ok:
            execution_code = ReasonCode.SPREAD_TOO_WIDE
            execution_reason = "spread multiple exceeds the configured maximum"
        elif not freshness_ok:
            execution_code = ReasonCode.DATA_STALE
            execution_reason = "market data is stale, future-dated, or age-inconsistent"
        elif not stop_ok:
            execution_code = ReasonCode.STOP_INVALID
            execution_reason = "protective stop candidate is invalid for direction"
        else:
            execution_code = ReasonCode.EXECUTION_PASS
            execution_reason = "spread, freshness, and stop checks pass"

        return SetupEvaluation(
            catalyst=GateResult(catalyst_code, catalyst_passed, catalyst_reason),
            acceptance=GateResult(acceptance_code, acceptance_passed, acceptance_reason),
            confirmation=GateResult(
                confirmation_code,
                confirmation_passed,
                confirmation_reason,
            ),
            execution=GateResult(execution_code, execution_passed, execution_reason),
            direction=direction,
        )

    @staticmethod
    def _stop_is_valid(direction: Direction | None, market: MarketSnapshot) -> bool:
        if direction is Direction.LONG:
            return market.stop_candidate < market.ask
        if direction is Direction.SHORT:
            return market.stop_candidate > market.bid
        return False
