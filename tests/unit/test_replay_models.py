"""Validation tests for raw replay contracts and strict JSON fixtures."""

from copy import deepcopy
from json import load
from pathlib import Path
from unittest import TestCase

from catalyst.replay.fixture import load_replay_fixture, parse_replay_fixture

ROOT = Path(__file__).resolve().parents[2]
LONG_PATH = ROOT / "tests" / "data" / "replay" / "long_pass.json"


def raw_long() -> dict:
    with LONG_PATH.open("r", encoding="utf-8") as handle:
        return load(handle)


class ReplayFixtureTests(TestCase):
    def test_valid_fixture_parses_exact_decimal_and_utc_values(self) -> None:
        fixture = load_replay_fixture(LONG_PATH)

        self.assertEqual(fixture.scenario.scenario_id, "long_pass")
        self.assertEqual(str(fixture.scenario.ticks[0].bid), "99.8")
        self.assertEqual(fixture.scenario.ticks[0].timestamp.utcoffset().total_seconds(), 0)

    def test_decimal_json_number_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["ticks"][0]["bid"] = 99.8

        with self.assertRaisesRegex(ValueError, "non-empty string"):
            parse_replay_fixture(raw)

    def test_non_utc_timestamp_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["ticks"][0]["timestamp"] = "2030-01-10T14:00:00+01:00"

        with self.assertRaisesRegex(ValueError, "normalized to UTC"):
            parse_replay_fixture(raw)

    def test_duplicate_tick_identity_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["ticks"].append(deepcopy(raw["scenario"]["ticks"][0]))

        with self.assertRaisesRegex(ValueError, "identities must be unique"):
            parse_replay_fixture(raw)

    def test_crossed_quote_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["ticks"][0]["ask"] = "99.0"

        with self.assertRaisesRegex(ValueError, "greater than or equal"):
            parse_replay_fixture(raw)

    def test_unknown_key_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["force_live"] = True

        with self.assertRaisesRegex(ValueError, "unknown keys"):
            parse_replay_fixture(raw)

    def test_sub_microsecond_delay_is_rejected(self) -> None:
        raw = raw_long()
        raw["scenario"]["evaluation_delay_seconds"] = "0.0000001"

        with self.assertRaisesRegex(ValueError, "at most six decimals"):
            parse_replay_fixture(raw)

    def test_execution_slippage_cannot_exceed_sized_allowance(self) -> None:
        raw = raw_long()
        raw["scenario"]["execution"]["maximum_adverse_slippage_ticks"] = "2"

        with self.assertRaisesRegex(ValueError, "sized contract allowance"):
            parse_replay_fixture(raw)
