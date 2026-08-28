"""Stable clock ordering and executable-side replay execution tests."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from catalyst.replay.clock import ClockItemKind, ReplayClock
from catalyst.replay.execution import ReplayExecutionModel
from catalyst.replay.fixture import load_replay_fixture
from catalyst.replay.models import ExecutionScenario, ExecutionStatus
from catalyst.replay.runner import ReplayRunner

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data" / "replay"


class ReplayClockTests(TestCase):
    def test_input_order_does_not_change_total_order(self) -> None:
        scenario = load_replay_fixture(DATA / "long_pass.json").scenario
        clock = ReplayClock()
        forward = clock.timeline(scenario.event, scenario.ticks, scenario.bars)
        reverse = clock.timeline(
            scenario.event,
            tuple(reversed(scenario.ticks)),
            tuple(reversed(scenario.bars)),
        )

        forward_keys = tuple(
            (item.timestamp, item.kind, item.symbol, item.source_sequence) for item in forward
        )
        reverse_keys = tuple(
            (item.timestamp, item.kind, item.symbol, item.source_sequence) for item in reverse
        )
        self.assertEqual(forward_keys, reverse_keys)
        same_time = [item.kind for item in forward if item.timestamp == scenario.event.scheduled_at]
        self.assertEqual(same_time, [ClockItemKind.EVENT, ClockItemKind.BAR_CLOSE])


class ReplayExecutionTests(TestCase):
    def setUp(self) -> None:
        self.fixture = load_replay_fixture(DATA / "long_pass.json")
        result = ReplayRunner().run(self.fixture)
        assert result.decision.plan is not None
        self.plan = result.decision.plan
        self.model = ReplayExecutionModel()

    def test_long_fill_uses_ask_after_latency(self) -> None:
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            self.fixture.scenario.execution,
        )

        self.assertEqual(result.fill_price, Decimal("101.5"))
        self.assertEqual(result.adverse_slippage_ticks, Decimal("1"))

    def test_zero_latency_uses_current_executable_ask(self) -> None:
        execution = replace(self.fixture.scenario.execution, latency_milliseconds=0)
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            execution,
        )

        self.assertEqual(result.fill_price, Decimal("101.4"))

    def test_rejection_is_explicit_and_unfilled(self) -> None:
        execution = replace(self.fixture.scenario.execution, rejection_code="BROKER_REJECT")
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            execution,
        )

        self.assertEqual(result.status, ExecutionStatus.REJECTED)
        self.assertEqual(result.filled_quantity, Decimal("0"))

    def test_adverse_slippage_misses_fill(self) -> None:
        execution = replace(
            self.fixture.scenario.execution,
            maximum_adverse_slippage_ticks=Decimal("0"),
        )
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            execution,
        )

        self.assertEqual(result.code, "ADVERSE_SLIPPAGE_LIMIT")
        self.assertEqual(result.status, ExecutionStatus.MISSED)

    def test_partial_fill_rounds_down_to_volume_step(self) -> None:
        execution = ExecutionScenario(100, Decimal("1"), Decimal("0.5"))
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            execution,
        )

        self.assertEqual(result.status, ExecutionStatus.PARTIAL)
        self.assertEqual(result.filled_quantity, Decimal("0.3"))

    def test_partial_fill_below_broker_minimum_is_missed(self) -> None:
        execution = ExecutionScenario(100, Decimal("1"), Decimal("0.01"))
        result = self.model.execute(
            self.plan,
            self.fixture.scenario.ticks,
            self.fixture.scenario.contract,
            execution,
        )

        self.assertEqual(result.status, ExecutionStatus.MISSED)
        self.assertEqual(result.code, "PARTIAL_FILL_BELOW_MINIMUM")

    def test_short_fill_uses_bid_after_latency(self) -> None:
        fixture = load_replay_fixture(DATA / "short_pass.json")
        replay = ReplayRunner().run(fixture)

        self.assertIsNotNone(replay.execution)
        assert replay.execution is not None
        self.assertEqual(replay.execution.fill_price, Decimal("92.7"))

    def test_missing_quote_is_a_missed_fill(self) -> None:
        result = self.model.execute(
            self.plan,
            (),
            self.fixture.scenario.contract,
            self.fixture.scenario.execution,
        )

        self.assertEqual(result.code, "NO_EXECUTABLE_QUOTE")
        self.assertEqual(result.status, ExecutionStatus.MISSED)
