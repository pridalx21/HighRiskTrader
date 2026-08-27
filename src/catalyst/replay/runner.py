"""End-to-end deterministic replay through the public decision pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from catalyst.config import RuntimeConfig
from catalyst.domain.enums import Direction
from catalyst.domain.models import PipelineDecision
from catalyst.domain.serialization import sha256_canonical
from catalyst.engine.exit_engine import (
    ExitDecision,
    ExitQuote,
    IntradayExitEngine,
    ManagedPosition,
)
from catalyst.engine.pipeline import DecisionPipeline
from catalyst.replay.clock import ReplayClock
from catalyst.replay.execution import ReplayExecutionModel
from catalyst.replay.features import FeatureBuildResult, MarketFeatureBuilder
from catalyst.replay.models import ExecutionResult, ExecutionStatus, RawTick, ReplayFixture

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ReplayResult:
    scenario_id: str
    fixture_hash: str
    fixture: ReplayFixture
    features: FeatureBuildResult
    decision: PipelineDecision
    execution: ExecutionResult | None
    exit: ExitDecision | None
    gross_pnl: Decimal
    commission: Decimal
    net_pnl: Decimal
    net_r_multiple: Decimal
    expected_match: bool


class ReplayRunner:
    """Run raw evidence through feature, decision, execution, and exit cores."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()
        self.features = MarketFeatureBuilder(self.config)
        self.pipeline = DecisionPipeline(self.config)
        self.execution = ReplayExecutionModel()
        self.exits = IntradayExitEngine()
        self.clock = ReplayClock()

    def run(self, fixture: ReplayFixture) -> ReplayResult:
        scenario = fixture.scenario
        self.clock.timeline(scenario.event, scenario.ticks, scenario.bars)
        features = self.features.build(scenario)
        decision = self.pipeline.evaluate(
            scenario.event,
            features.snapshot,
            scenario.account,
            features.evaluation_at,
            contract=scenario.contract,
            auto_demo_armed=True,
        )
        execution: ExecutionResult | None = None
        exit_decision: ExitDecision | None = None
        gross_pnl = ZERO
        commission = ZERO
        net_pnl = ZERO
        net_r = ZERO

        if decision.plan is not None:
            execution = self.execution.execute(
                decision.plan,
                scenario.ticks,
                scenario.contract,
                scenario.execution,
            )
            if execution.status in (
                ExecutionStatus.FILLED,
                ExecutionStatus.PARTIAL,
            ):
                if execution.fill_price is None or execution.fill_timestamp is None:
                    raise RuntimeError("filled execution lacks price or timestamp")
                position = ManagedPosition(
                    symbol=decision.plan.symbol,
                    direction=decision.plan.direction,
                    entry=execution.fill_price,
                    initial_stop=decision.plan.stop,
                    current_stop=decision.plan.stop,
                    quantity=execution.filled_quantity,
                    opened_at=execution.fill_timestamp,
                    pre_event_high=features.evidence.pre_event_high,
                    pre_event_low=features.evidence.pre_event_low,
                    session_cutoff=scenario.session_cutoff,
                )
                exit_decision = self._find_exit(
                    position,
                    scenario.ticks,
                    scenario.emergency_exit,
                )
                if exit_decision is None:
                    raise RuntimeError(
                        "filled replay position has no deterministic intraday exit"
                    )
                if exit_decision.exit_price is None:
                    raise RuntimeError("exit decision lacks executable price")
                gross_pnl = self._gross_pnl(
                    position,
                    exit_decision.exit_price,
                    scenario.contract.tick_size,
                    scenario.contract.tick_value,
                    scenario.contract.profit_to_account_rate,
                )
                commission = execution.commission
                net_pnl = gross_pnl - commission
                net_r = net_pnl / decision.plan.risk_amount

        result = ReplayResult(
            scenario_id=scenario.scenario_id,
            fixture_hash=sha256_canonical(scenario),
            fixture=fixture,
            features=features,
            decision=decision,
            execution=execution,
            exit=exit_decision,
            gross_pnl=gross_pnl,
            commission=commission,
            net_pnl=net_pnl,
            net_r_multiple=net_r,
            expected_match=False,
        )
        return replace(result, expected_match=self._matches_expected(result, fixture))

    def _find_exit(
        self,
        position: ManagedPosition,
        ticks: tuple[RawTick, ...],
        emergency_exit: bool,
    ) -> ExitDecision | None:
        first = True
        for tick in self.clock.ticks(ticks, position.symbol):
            if tick.timestamp <= position.opened_at:
                continue
            decision = self.exits.evaluate(
                position,
                ExitQuote(tick.symbol, tick.timestamp, tick.bid, tick.ask),
                tick.timestamp,
                maximum_data_age_seconds=self.config.strategy.maximum_data_age_seconds,
                emergency=emergency_exit and first,
            )
            first = False
            if decision.should_exit:
                return decision
        return None

    @staticmethod
    def _gross_pnl(
        position: ManagedPosition,
        exit_price: Decimal,
        tick_size: Decimal,
        tick_value: Decimal,
        conversion_rate: Decimal,
    ) -> Decimal:
        if position.direction is Direction.LONG:
            price_change = exit_price - position.entry
        else:
            price_change = position.entry - exit_price
        return (
            price_change
            / tick_size
            * tick_value
            * conversion_rate
            * position.quantity
        )

    @staticmethod
    def _matches_expected(result: ReplayResult, fixture: ReplayFixture) -> bool:
        expected = fixture.expected
        execution_status = result.execution.status if result.execution else None
        exit_reason = result.exit.reason.value if result.exit else None
        return (
            result.decision.code.value == expected.decision_code
            and result.decision.setup.direction is expected.direction
            and execution_status is expected.execution_status
            and exit_reason == expected.exit_reason
        )
