"""Continuous demo runtime composition shared by the MT5 CLI and tests.

The runtime deliberately keeps the deterministic decision core unchanged. Live
market data is normalized into the same replay contracts before the public
DecisionPipeline is called. Shadow mode may evaluate as virtually armed while
the broker stays physically disarmed; demo-auto mode requires the broker to be
explicitly armed through the operator control plane.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError, load
from pathlib import Path
from typing import Any

from catalyst.adapters.guarded_demo_broker import GuardedDemoBroker
from catalyst.adapters.mt5_observability import MT5ReadAdapter
from catalyst.adapters.sqlite_journal import JournalConflictError, SQLiteJournal
from catalyst.config import RuntimeConfig
from catalyst.domain.enums import EventImportance, EventStatus
from catalyst.domain.models import EconomicEvent, PipelineDecision, TradePlan
from catalyst.engine.durable_execution import DurableDemoExecutor, DurableSubmissionResult
from catalyst.engine.pipeline import DecisionPipeline
from catalyst.replay.features import FeatureBuildResult, MarketFeatureBuilder
from catalyst.replay.models import CrossAssetRule, ExecutionScenario, ReplayScenario


@dataclass(frozen=True, slots=True)
class LivePrimaryRules:
    related: tuple[CrossAssetRule, ...]

    def __post_init__(self) -> None:
        if not self.related:
            raise ValueError("each live primary requires at least one related-market rule")


@dataclass(frozen=True, slots=True)
class LiveRuntimeConfig:
    primaries: Mapping[str, LivePrimaryRules]
    poll_seconds: Decimal = Decimal("1")
    bar_seconds: int = 60
    session_cutoff_minutes: int = 120

    def __post_init__(self) -> None:
        if not self.primaries:
            raise ValueError("live runtime requires at least one primary symbol")
        if any(not symbol.strip() for symbol in self.primaries):
            raise ValueError("live primary symbols must not be empty")
        if not self.poll_seconds.is_finite() or self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be finite and positive")
        if self.bar_seconds <= 0:
            raise ValueError("bar_seconds must be positive")
        if self.session_cutoff_minutes <= 0:
            raise ValueError("session_cutoff_minutes must be positive")


def _decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal string") from exc
    if not result.is_finite() or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise ValueError(f"{field_name} must be {qualifier}")
    return result


def load_live_runtime_config(path: str | Path) -> LiveRuntimeConfig:
    """Load the explicit live cross-asset rules used by the MT5 runner."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw: Any = load(handle)
    except JSONDecodeError as exc:
        raise ValueError(f"invalid live runtime JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("live runtime root must be an object")
    expected = {"poll_seconds", "bar_seconds", "session_cutoff_minutes", "primaries"}
    if set(raw) != expected:
        raise ValueError("live runtime JSON has missing or unknown root keys")
    primaries_raw = raw["primaries"]
    if not isinstance(primaries_raw, dict) or not primaries_raw:
        raise ValueError("primaries must be a non-empty object")

    primaries: dict[str, LivePrimaryRules] = {}
    for primary, primary_raw in primaries_raw.items():
        if not isinstance(primary, str) or not primary.strip():
            raise ValueError("primary symbol names must be non-empty strings")
        if not isinstance(primary_raw, dict) or set(primary_raw) != {"related"}:
            raise ValueError(f"primary {primary} must contain only related")
        related_raw = primary_raw["related"]
        if not isinstance(related_raw, list) or not related_raw:
            raise ValueError(f"primary {primary} related must be a non-empty array")
        related: list[CrossAssetRule] = []
        for index, item in enumerate(related_raw):
            if not isinstance(item, dict) or set(item) != {"symbol", "polarity", "minimum_move"}:
                raise ValueError(f"primary {primary} related[{index}] has an invalid schema")
            symbol = item["symbol"]
            polarity = item["polarity"]
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("related symbol must be a non-empty string")
            if type(polarity) is not int:
                raise ValueError("related polarity must be an integer")
            related.append(
                CrossAssetRule(
                    symbol=symbol,
                    polarity=polarity,
                    minimum_move=_decimal(
                        item["minimum_move"],
                        f"primaries.{primary}.related[{index}].minimum_move",
                        positive=True,
                    ),
                )
            )
        primaries[primary] = LivePrimaryRules(tuple(related))

    bar_seconds = raw["bar_seconds"]
    cutoff = raw["session_cutoff_minutes"]
    if type(bar_seconds) is not int or type(cutoff) is not int:
        raise ValueError("bar_seconds and session_cutoff_minutes must be integers")
    return LiveRuntimeConfig(
        primaries=primaries,
        poll_seconds=_decimal(raw["poll_seconds"], "poll_seconds", positive=True),
        bar_seconds=bar_seconds,
        session_cutoff_minutes=cutoff,
    )


@dataclass(frozen=True, slots=True)
class RuntimeCycleResult:
    event_id: str
    symbol: str
    decision: PipelineDecision | None
    submission: DurableSubmissionResult | None
    error: str | None = None


class CatalystRuntime:
    """Evaluate active calendar events against live MT5 data one cycle at a time."""

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        live_config: LiveRuntimeConfig,
        journal: SQLiteJournal,
        broker: GuardedDemoBroker,
        market_data: MT5ReadAdapter,
        events: tuple[EconomicEvent, ...],
        auto_demo: bool,
    ) -> None:
        self.config = config
        self.live_config = live_config
        self.journal = journal
        self.broker = broker
        self.market_data = market_data
        self.events = tuple(sorted(events, key=lambda item: (item.scheduled_at, item.event_id)))
        self.auto_demo = auto_demo
        self.pipeline = DecisionPipeline(config)
        self.features = MarketFeatureBuilder(config)
        self.executor = DurableDemoExecutor(journal)
        self._reported: set[tuple[str, str, str]] = set()

    def active_events(self, now: datetime) -> tuple[EconomicEvent, ...]:
        self._require_utc(now)
        start = now - self.config.state_machine.entry_deadline
        end = now + self.config.state_machine.pre_arm
        return tuple(
            event
            for event in self.events
            if event.importance is EventImportance.HIGH
            and event.status is EventStatus.SCHEDULED
            and start <= event.scheduled_at <= end
        )

    def cycle(self, *, now: datetime) -> tuple[RuntimeCycleResult, ...]:
        self._require_utc(now)
        results: list[RuntimeCycleResult] = []
        for event in self.active_events(now):
            if now < event.scheduled_at + self.config.state_machine.shock_window:
                continue
            if now > event.scheduled_at + self.config.state_machine.entry_deadline:
                continue
            for symbol, primary_rules in sorted(self.live_config.primaries.items()):
                if symbol not in event.eligible_symbols:
                    continue
                try:
                    account = self.broker.account_snapshot()
                    contract = self.broker.contract_for(symbol)
                    feature = self._live_features(
                        event=event,
                        symbol=symbol,
                        rules=primary_rules.related,
                        account=account,
                        contract=contract,
                        now=now,
                    )
                    decision = self.pipeline.evaluate(
                        event,
                        feature.snapshot,
                        account,
                        now,
                        contract=contract,
                        auto_demo_armed=self.broker.armed if self.auto_demo else True,
                    )
                    submission = self._handle_decision(event, decision, now)
                    results.append(RuntimeCycleResult(event.event_id, symbol, decision, submission))
                except Exception as exc:
                    self.broker.disarm() if self.auto_demo else None
                    self._heartbeat(
                        now=now,
                        status="runtime_error",
                        details={
                            "event_id": event.event_id,
                            "symbol": symbol,
                            "exception_type": type(exc).__name__,
                        },
                    )
                    results.append(
                        RuntimeCycleResult(
                            event.event_id,
                            symbol,
                            None,
                            None,
                            f"{type(exc).__name__}: {exc}",
                        )
                    )
        return tuple(results)

    def _live_features(
        self,
        *,
        event: EconomicEvent,
        symbol: str,
        rules: tuple[CrossAssetRule, ...],
        account: Any,
        contract: Any,
        now: datetime,
    ) -> FeatureBuildResult:
        history_start = event.scheduled_at - self.config.pre_event_range
        primary_ticks = self.market_data.ticks_between(symbol, history_start, now)
        latest = self.market_data.latest_tick(
            symbol,
            at=now,
            maximum_age=timedelta(seconds=float(self.config.strategy.maximum_data_age_seconds)),
        )
        if not primary_ticks or primary_ticks[-1].timestamp < latest.timestamp:
            primary_ticks = (*primary_ticks, latest)
        bars = self.market_data.bars_between(
            symbol,
            history_start,
            event.scheduled_at,
            timeframe_seconds=self.live_config.bar_seconds,
        )
        ticks = list(primary_ticks)
        for rule in rules:
            ticks.extend(self.market_data.ticks_between(rule.symbol, history_start, now))

        base = ReplayScenario(
            scenario_id=f"live:{event.event_id}:{symbol}",
            event=event,
            primary_symbol=symbol,
            ticks=tuple(ticks),
            bars=bars,
            related_rules=rules,
            account=account,
            contract=contract,
            execution=ExecutionScenario(0, Decimal("0")),
            evaluation_delay_seconds=Decimal("0"),
            session_cutoff=event.scheduled_at
            + timedelta(minutes=self.live_config.session_cutoff_minutes),
            market_open=True,
        )
        first = self.features.build(base)
        delay = now - first.snapshot.timestamp
        if delay < timedelta(0):
            raise RuntimeError("live feature timestamp is in the future")
        delay_seconds = Decimal(delay.days * 86400 + delay.seconds) + (
            Decimal(delay.microseconds) / Decimal("1000000")
        )
        if delay_seconds == 0:
            return first
        adjusted = ReplayScenario(
            scenario_id=base.scenario_id,
            event=base.event,
            primary_symbol=base.primary_symbol,
            ticks=base.ticks,
            bars=base.bars,
            related_rules=base.related_rules,
            account=base.account,
            contract=base.contract,
            execution=base.execution,
            evaluation_delay_seconds=delay_seconds,
            session_cutoff=base.session_cutoff,
            market_open=base.market_open,
        )
        return self.features.build(adjusted)

    def _handle_decision(
        self,
        event: EconomicEvent,
        decision: PipelineDecision,
        now: datetime,
    ) -> DurableSubmissionResult | None:
        code = str(decision.code)
        signature = (event.event_id, decision.setup.direction.value if decision.setup.direction else "none", code)
        if signature not in self._reported:
            self._reported.add(signature)
            self._heartbeat(
                now=now,
                status="decision",
                details={
                    "event_id": event.event_id,
                    "code": code,
                    "state": decision.state,
                    "reason": decision.reason,
                },
            )
        plan = decision.plan
        if plan is None:
            return None
        self._record_plan_decision(event, plan, decision, now)
        if not self.auto_demo:
            return None
        if not self.broker.armed:
            raise RuntimeError("demo-auto runtime reached a plan while broker is disarmed")
        result = self.executor.submit_once(plan, self.broker, occurred_at=now)
        if result.requires_reconciliation:
            self.broker.disarm()
        return result

    def _record_plan_decision(
        self,
        event: EconomicEvent,
        plan: TradePlan,
        decision: PipelineDecision,
        now: datetime,
    ) -> None:
        try:
            self.journal.record_decision(
                event_id=event.event_id,
                decision_id=plan.decision_id,
                decision=decision,
                occurred_at=now,
            )
        except JournalConflictError:
            # A stable plan identity may already have been persisted by a previous
            # poll or process. DurableDemoExecutor then enforces at-most-once send.
            pass

    def _heartbeat(self, *, now: datetime, status: str, details: Mapping[str, Any]) -> None:
        self.journal.record_heartbeat(
            component="runtime",
            status=status,
            occurred_at=now,
            details=details,
        )

    @staticmethod
    def _require_utc(now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("runtime timestamps must be timezone-aware UTC")


def utc_now() -> datetime:
    return datetime.now(UTC)
