"""Fail-closed intraday exit rules and executable-side pricing."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import Direction
from catalyst.engine.exit_engine import (
    ExitQuote,
    ExitReason,
    IntradayExitEngine,
    ManagedPosition,
)


class IntradayExitEngineTests(TestCase):
    def setUp(self) -> None:
        self.opened = datetime(2030, 1, 10, 13, 32, tzinfo=UTC)
        self.cutoff = datetime(2030, 1, 10, 13, 40, tzinfo=UTC)
        self.position = ManagedPosition(
            "PRIMARY",
            Direction.LONG,
            Decimal("101.5"),
            Decimal("95.0"),
            Decimal("95.0"),
            Decimal("0.7"),
            self.opened,
            Decimal("100.0"),
            Decimal("95.0"),
            self.cutoff,
        )
        self.engine = IntradayExitEngine()

    def evaluate(self, quote: ExitQuote, **kwargs):
        return self.engine.evaluate(
            self.position,
            quote,
            quote.timestamp,
            maximum_data_age_seconds=Decimal("2"),
            **kwargs,
        )

    def test_long_stop_exits_on_bid(self) -> None:
        quote = ExitQuote(
            "PRIMARY",
            self.opened + timedelta(seconds=1),
            Decimal("94.9"),
            Decimal("95.1"),
        )
        result = self.evaluate(quote)

        self.assertEqual(result.reason, ExitReason.PROTECTIVE_STOP)
        self.assertEqual(result.exit_price, Decimal("94.9"))

    def test_short_stop_exits_on_ask(self) -> None:
        position = ManagedPosition(
            "PRIMARY", Direction.SHORT, Decimal("92.7"), Decimal("100"),
            Decimal("100"), Decimal("0.6"), self.opened, Decimal("100"),
            Decimal("95"), self.cutoff,
        )
        quote = ExitQuote(
            "PRIMARY",
            self.opened + timedelta(seconds=1),
            Decimal("99.9"),
            Decimal("100.1"),
        )
        result = self.engine.evaluate(
            position, quote, quote.timestamp, maximum_data_age_seconds=Decimal("2")
        )

        self.assertEqual(result.reason, ExitReason.PROTECTIVE_STOP)
        self.assertEqual(result.exit_price, Decimal("100.1"))

    def test_range_reclaim_exits(self) -> None:
        quote = ExitQuote(
            "PRIMARY",
            self.opened + timedelta(seconds=1),
            Decimal("99.8"),
            Decimal("100.0"),
        )

        self.assertEqual(self.evaluate(quote).reason, ExitReason.RANGE_RECLAIM)

    def test_emergency_precedes_stop(self) -> None:
        quote = ExitQuote(
            "PRIMARY",
            self.opened + timedelta(seconds=1),
            Decimal("94.9"),
            Decimal("95.1"),
        )

        self.assertEqual(self.evaluate(quote, emergency=True).reason, ExitReason.EMERGENCY)

    def test_cutoff_exits_outside_range(self) -> None:
        quote = ExitQuote("PRIMARY", self.cutoff, Decimal("102.0"), Decimal("102.2"))

        self.assertEqual(self.evaluate(quote).reason, ExitReason.SESSION_CUTOFF)

    def test_stale_quote_fails_closed(self) -> None:
        quote = ExitQuote("PRIMARY", self.opened, Decimal("102.0"), Decimal("102.2"))

        with self.assertRaisesRegex(ValueError, "stale"):
            self.engine.evaluate(
                self.position,
                quote,
                self.opened + timedelta(seconds=3),
                maximum_data_age_seconds=Decimal("2"),
            )

    def test_stop_cannot_be_widened(self) -> None:
        with self.assertRaisesRegex(ValueError, "never be widened"):
            replace(self.position, current_stop=Decimal("94.9"))
