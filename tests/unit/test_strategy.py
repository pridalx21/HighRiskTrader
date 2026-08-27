from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import Direction, EventImportance, EventStatus, ReasonCode
from catalyst.strategy.event_reaction_retest import EventReactionRetestStrategy
from tests.fixtures import EVENT_TIME, READY_TIME, event, long_market


class EventReactionRetestStrategyTests(TestCase):
    def setUp(self) -> None:
        self.strategy = EventReactionRetestStrategy()

    def test_all_four_gates_pass_for_long_fixture(self) -> None:
        result = self.strategy.evaluate(event(), long_market(), READY_TIME)
        self.assertTrue(result.all_green)
        self.assertEqual(result.direction, Direction.LONG)
        self.assertEqual(result.catalyst.code, ReasonCode.CATALYST_PASS)
        self.assertEqual(result.acceptance.code, ReasonCode.ACCEPTANCE_PASS)
        self.assertEqual(result.confirmation.code, ReasonCode.CONFIRMATION_PASS)
        self.assertEqual(result.execution.code, ReasonCode.EXECUTION_PASS)

    def test_shock_window_blocks_catalyst(self) -> None:
        now = EVENT_TIME + timedelta(seconds=30)
        result = self.strategy.evaluate(event(), long_market(), now)
        self.assertFalse(result.catalyst.passed)
        self.assertIn("shock", result.catalyst.reason)
        self.assertEqual(result.catalyst.code, ReasonCode.SHOCK_WINDOW_ACTIVE)

    def test_price_inside_range_blocks_acceptance(self) -> None:
        market = replace(long_market(), bid=Decimal("98.9"), ask=Decimal("99.1"))
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertIsNone(result.direction)
        self.assertFalse(result.acceptance.passed)
        self.assertEqual(result.acceptance.code, ReasonCode.PRICE_INSIDE_RANGE)

    def test_missing_cross_asset_votes_blocks_confirmation(self) -> None:
        market = replace(
            long_market(),
            related_markets_observed=2,
            cross_asset_confirmations=1,
        )
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertFalse(result.confirmation.passed)
        self.assertEqual(result.confirmation.code, ReasonCode.CONFIRMATION_INSUFFICIENT)

    def test_stale_data_blocks_execution(self) -> None:
        market = replace(
            long_market(),
            timestamp=READY_TIME - timedelta(seconds=2, milliseconds=100),
            data_age_seconds=Decimal("2.1"),
        )
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertFalse(result.execution.passed)
        self.assertIn("stale", result.execution.reason)
        self.assertEqual(result.execution.code, ReasonCode.DATA_STALE)

    def test_inconsistent_market_data_age_blocks_execution(self) -> None:
        market = replace(long_market(), data_age_seconds=Decimal("0.1"))
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertFalse(result.execution.passed)
        self.assertEqual(result.execution.code, ReasonCode.DATA_STALE)

    def test_spread_spike_blocks_execution(self) -> None:
        market = replace(long_market(), ask=Decimal("101.3"))
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertFalse(result.execution.passed)
        self.assertIn("spread", result.execution.reason)
        self.assertEqual(result.execution.code, ReasonCode.SPREAD_TOO_WIDE)

    def test_short_direction_requires_stop_above_entry(self) -> None:
        market = replace(
            long_market(),
            bid=Decimal("94.0"),
            ask=Decimal("94.1"),
            stop_candidate=Decimal("95.3"),
        )
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertTrue(result.all_green)
        self.assertEqual(result.direction, Direction.SHORT)

    def test_cancelled_event_is_rejected(self) -> None:
        result = self.strategy.evaluate(
            replace(event(), status=EventStatus.CANCELLED),
            long_market(),
            READY_TIME,
        )
        self.assertFalse(result.catalyst.passed)
        self.assertEqual(result.catalyst.code, ReasonCode.EVENT_NOT_ELIGIBLE)

    def test_low_importance_event_is_rejected(self) -> None:
        result = self.strategy.evaluate(
            replace(event(), importance=EventImportance.LOW),
            long_market(),
            READY_TIME,
        )
        self.assertFalse(result.catalyst.passed)
        self.assertEqual(result.catalyst.code, ReasonCode.EVENT_NOT_HIGH_IMPORTANCE)

    def test_expired_event_has_stable_reason_code(self) -> None:
        now = EVENT_TIME + timedelta(minutes=16)
        market = replace(
            long_market(),
            timestamp=now - timedelta(milliseconds=200),
        )
        result = self.strategy.evaluate(event(), market, now)
        self.assertFalse(result.catalyst.passed)
        self.assertEqual(result.catalyst.code, ReasonCode.ENTRY_WINDOW_EXPIRED)

    def test_unmapped_symbol_is_rejected(self) -> None:
        result = self.strategy.evaluate(
            replace(event(), eligible_symbols=("US500",)),
            long_market(),
            READY_TIME,
        )
        self.assertFalse(result.catalyst.passed)
        self.assertEqual(result.catalyst.code, ReasonCode.SYMBOL_NOT_MAPPED)

    def test_invalid_retest_has_stable_reason_code(self) -> None:
        result = self.strategy.evaluate(
            event(),
            replace(long_market(), retest_holds=False),
            READY_TIME,
        )
        self.assertFalse(result.acceptance.passed)
        self.assertEqual(result.acceptance.code, ReasonCode.RETEST_INVALID)

    def test_too_few_related_markets_has_stable_reason_code(self) -> None:
        market = replace(
            long_market(),
            related_markets_observed=1,
            cross_asset_confirmations=1,
        )
        result = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertFalse(result.confirmation.passed)
        self.assertEqual(result.confirmation.code, ReasonCode.RELATED_MARKETS_MISSING)

    def test_closed_market_is_rejected(self) -> None:
        result = self.strategy.evaluate(
            event(),
            replace(long_market(), market_open=False),
            READY_TIME,
        )
        self.assertFalse(result.execution.passed)
        self.assertEqual(result.execution.code, ReasonCode.MARKET_CLOSED)

    def test_wrong_side_stop_has_stable_reason_code(self) -> None:
        result = self.strategy.evaluate(
            event(),
            replace(long_market(), stop_candidate=Decimal("102")),
            READY_TIME,
        )
        self.assertFalse(result.execution.passed)
        self.assertEqual(result.execution.code, ReasonCode.STOP_INVALID)
