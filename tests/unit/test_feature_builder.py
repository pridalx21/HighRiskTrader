"""Exact feature reconstruction from raw bid/ask fixtures."""

from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from catalyst.domain.enums import Direction
from catalyst.replay.features import MarketFeatureBuilder
from catalyst.replay.fixture import load_replay_fixture
from catalyst.replay.models import FeatureStatus

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data" / "replay"


class MarketFeatureBuilderTests(TestCase):
    def build(self, name: str):
        return MarketFeatureBuilder().build(load_replay_fixture(DATA / f"{name}.json").scenario)

    def test_long_features_are_exact(self) -> None:
        result = self.build("long_pass")

        self.assertEqual(result.evidence.status, FeatureStatus.READY)
        self.assertEqual(result.evidence.breakout_direction, Direction.LONG)
        self.assertEqual(result.evidence.pre_event_high, Decimal("100.0"))
        self.assertEqual(result.evidence.pre_event_low, Decimal("95.0"))
        self.assertEqual(result.evidence.baseline_spread, Decimal("0.2"))
        self.assertEqual(result.evidence.atr, Decimal("4.8"))
        self.assertEqual(result.snapshot.cross_asset_confirmations, 2)

    def test_short_features_and_votes_are_exact(self) -> None:
        result = self.build("short_pass")

        self.assertEqual(result.evidence.status, FeatureStatus.READY)
        self.assertEqual(result.evidence.breakout_direction, Direction.SHORT)
        self.assertEqual(
            tuple(vote.direction for vote in result.evidence.votes),
            (Direction.SHORT, Direction.SHORT),
        )

    def test_whipsaw_preserves_first_breakout_evidence(self) -> None:
        result = self.build("whipsaw")

        self.assertEqual(result.evidence.status, FeatureStatus.WHIPSAW)
        self.assertEqual(result.evidence.breakout_direction, Direction.LONG)
        self.assertFalse(result.snapshot.retest_holds)

    def test_stale_delay_is_exact_without_binary_float(self) -> None:
        result = self.build("stale_data")

        self.assertEqual(result.snapshot.data_age_seconds, Decimal("3"))
        self.assertEqual(
            (result.evaluation_at - result.snapshot.timestamp).total_seconds(),
            3,
        )

    def test_missing_market_does_not_cast_neutral_vote(self) -> None:
        result = self.build("missing_confirmation")

        self.assertEqual(result.snapshot.related_markets_observed, 1)
        self.assertEqual(len(result.evidence.votes), 1)
