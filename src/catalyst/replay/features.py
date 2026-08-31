"""Bid/ask-aware deterministic feature construction for replay and demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from catalyst.config import RuntimeConfig
from catalyst.domain.enums import Direction
from catalyst.domain.models import MarketSnapshot
from catalyst.replay.models import (
    CrossAssetRule,
    CrossAssetVote,
    FeatureEvidence,
    FeatureStatus,
    RawBar,
    RawTick,
    ReplayScenario,
)


@dataclass(frozen=True, slots=True)
class FeatureBuildResult:
    snapshot: MarketSnapshot
    evidence: FeatureEvidence
    evaluation_at: datetime


class MarketFeatureBuilder:
    """Build one reconstructable v1 snapshot from ordered raw inputs."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()

    def build(self, scenario: ReplayScenario) -> FeatureBuildResult:
        event = scenario.event
        primary_ticks = self._ticks_for(scenario.ticks, scenario.primary_symbol)
        range_start = event.scheduled_at - self.config.pre_event_range
        pre_ticks = tuple(
            tick for tick in primary_ticks if range_start <= tick.timestamp < event.scheduled_at
        )
        if len(pre_ticks) < 3:
            raise ValueError("at least three primary pre-event ticks are required")
        pre_event_high = max(tick.ask for tick in pre_ticks)
        pre_event_low = min(tick.bid for tick in pre_ticks)
        baseline_spread = median(tick.spread for tick in pre_ticks)
        if baseline_spread <= 0:
            raise ValueError("pre-event median spread must be positive")
        atr = self._atr(
            scenario.bars,
            scenario.primary_symbol,
            range_start,
            event.scheduled_at,
        )

        shock_end = event.scheduled_at + self.config.state_machine.shock_window
        post_ticks = tuple(tick for tick in primary_ticks if tick.timestamp >= shock_end)
        if not post_ticks:
            raise ValueError("at least one primary post-shock tick is required")
        status, direction, breakout, retest, hold, evaluation_tick = self._reaction(
            post_ticks,
            pre_event_high,
            pre_event_low,
            scenario.contract.tick_size,
        )
        delay_microseconds = int(scenario.evaluation_delay_seconds * Decimal("1000000"))
        evaluation_at = evaluation_tick.timestamp + timedelta(microseconds=delay_microseconds)
        data_age = scenario.evaluation_delay_seconds
        votes = self._votes(
            scenario.ticks,
            scenario.related_rules,
            event.scheduled_at,
            evaluation_at,
        )
        confirmations = (
            sum(vote.direction is direction for vote in votes) if direction is not None else 0
        )
        stop_candidate = pre_event_low if direction is not Direction.SHORT else pre_event_high
        evidence = FeatureEvidence(
            status=status,
            pre_event_high=pre_event_high,
            pre_event_low=pre_event_low,
            baseline_spread=baseline_spread,
            atr=atr,
            breakout_direction=direction,
            breakout_at=breakout.timestamp if breakout else None,
            retest_at=retest.timestamp if retest else None,
            hold_at=hold.timestamp if hold else None,
            votes=votes,
            reason=self._status_reason(status),
        )
        snapshot = MarketSnapshot(
            symbol=scenario.primary_symbol,
            timestamp=evaluation_tick.timestamp,
            bid=evaluation_tick.bid,
            ask=evaluation_tick.ask,
            pre_event_high=pre_event_high,
            pre_event_low=pre_event_low,
            atr=atr,
            baseline_spread=baseline_spread,
            data_age_seconds=data_age,
            retest_holds=status is FeatureStatus.READY,
            stop_candidate=stop_candidate,
            related_markets_observed=len(votes),
            cross_asset_confirmations=confirmations,
            market_open=scenario.market_open,
        )
        return FeatureBuildResult(snapshot, evidence, evaluation_at)

    @staticmethod
    def _ticks_for(ticks: tuple[RawTick, ...], symbol: str) -> tuple[RawTick, ...]:
        return tuple(
            sorted(
                (tick for tick in ticks if tick.symbol == symbol),
                key=lambda tick: (tick.timestamp, tick.source_sequence),
            )
        )

    @staticmethod
    def _atr(
        bars: tuple[RawBar, ...],
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> Decimal:
        selected = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.symbol == symbol and start <= bar.opened_at and bar.closed_at <= end
                ),
                key=lambda bar: (bar.opened_at, bar.source_sequence),
            )
        )
        if not selected:
            raise ValueError("at least one complete pre-event primary bar is required")
        true_ranges: list[Decimal] = []
        previous_close: Decimal | None = None
        for bar in selected:
            high = (bar.bid_high + bar.ask_high) / Decimal("2")
            low = (bar.bid_low + bar.ask_low) / Decimal("2")
            close = (bar.bid_close + bar.ask_close) / Decimal("2")
            candidates = [high - low]
            if previous_close is not None:
                candidates.extend((abs(high - previous_close), abs(low - previous_close)))
            true_ranges.append(max(candidates))
            previous_close = close
        atr = sum(true_ranges, Decimal("0")) / Decimal(len(true_ranges))
        if atr <= 0:
            raise ValueError("ATR evidence must be positive")
        return atr

    @staticmethod
    def _reaction(
        ticks: tuple[RawTick, ...],
        high: Decimal,
        low: Decimal,
        tick_size: Decimal,
    ) -> tuple[
        FeatureStatus,
        Direction | None,
        RawTick | None,
        RawTick | None,
        RawTick | None,
        RawTick,
    ]:
        breakout: RawTick | None = None
        direction: Direction | None = None
        for tick in ticks:
            if tick.mid > high:
                breakout = tick
                direction = Direction.LONG
                break
            if tick.mid < low:
                breakout = tick
                direction = Direction.SHORT
                break
        if breakout is None or direction is None:
            return FeatureStatus.NO_BREAKOUT, None, None, None, None, ticks[-1]

        retest: RawTick | None = None
        for tick in ticks:
            if tick.timestamp <= breakout.timestamp:
                continue
            if direction is Direction.LONG:
                if tick.mid < low:
                    return FeatureStatus.WHIPSAW, direction, breakout, retest, None, tick
                if low <= tick.mid <= high:
                    return FeatureStatus.RANGE_RECLAIMED, direction, breakout, retest, None, tick
                if retest is None and high < tick.mid <= high + tick_size:
                    retest = tick
                    continue
                if retest is not None and tick.mid > high + tick_size:
                    return FeatureStatus.READY, direction, breakout, retest, tick, tick
            else:
                if tick.mid > high:
                    return FeatureStatus.WHIPSAW, direction, breakout, retest, None, tick
                if low <= tick.mid <= high:
                    return FeatureStatus.RANGE_RECLAIMED, direction, breakout, retest, None, tick
                if retest is None and low - tick_size <= tick.mid < low:
                    retest = tick
                    continue
                if retest is not None and tick.mid < low - tick_size:
                    return FeatureStatus.READY, direction, breakout, retest, tick, tick
        return FeatureStatus.NO_RETEST, direction, breakout, retest, None, ticks[-1]

    @staticmethod
    def _votes(
        ticks: tuple[RawTick, ...],
        rules: tuple[CrossAssetRule, ...],
        event_at: datetime,
        evaluation_at: datetime,
    ) -> tuple[CrossAssetVote, ...]:
        votes: list[CrossAssetVote] = []
        for rule in sorted(rules, key=lambda item: item.symbol):
            symbol_ticks = sorted(
                (tick for tick in ticks if tick.symbol == rule.symbol),
                key=lambda tick: (tick.timestamp, tick.source_sequence),
            )
            before = [tick for tick in symbol_ticks if tick.timestamp < event_at]
            after = [tick for tick in symbol_ticks if event_at <= tick.timestamp <= evaluation_at]
            if not before or not after:
                continue
            latest = after[-1]
            signed_move = (latest.mid - before[-1].mid) * Decimal(rule.polarity)
            if signed_move >= rule.minimum_move:
                direction: Direction | None = Direction.LONG
            elif signed_move <= -rule.minimum_move:
                direction = Direction.SHORT
            else:
                direction = None
            votes.append(
                CrossAssetVote(
                    symbol=rule.symbol,
                    direction=direction,
                    observed_at=latest.timestamp,
                    signed_move=signed_move,
                )
            )
        return tuple(votes)

    @staticmethod
    def _status_reason(status: FeatureStatus) -> str:
        reasons = {
            FeatureStatus.READY: "first breakout retest holds outside the range",
            FeatureStatus.NO_BREAKOUT: "no post-shock breakout was observed",
            FeatureStatus.NO_RETEST: "breakout has no completed first retest hold",
            FeatureStatus.RANGE_RECLAIMED: "price reclaimed the complete pre-event range",
            FeatureStatus.WHIPSAW: "both sides of the pre-event range broke",
            FeatureStatus.INSUFFICIENT_HISTORY: "raw history is insufficient",
        }
        return reasons[status]
