"""Seven expected outcomes and byte-stable complete replay reporting."""

from dataclasses import replace
from datetime import timedelta
from json import loads
from pathlib import Path
from unittest import TestCase

from catalyst.replay.fixture import load_replay_fixture
from catalyst.replay.report import build_replay_report, replay_report_json
from catalyst.replay.runner import ReplayRunner

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data" / "replay"


class ReplayPipelineIntegrationTests(TestCase):
    def run_all(self):
        runner = ReplayRunner()
        return tuple(
            runner.run(load_replay_fixture(path))
            for path in sorted(DATA.glob("*.json"))
        )

    def test_all_seven_synthetic_outcomes_match_exactly(self) -> None:
        results = self.run_all()

        self.assertEqual(len(results), 7)
        self.assertTrue(all(result.expected_match for result in results))
        accepted = [result for result in results if result.execution is not None]
        self.assertEqual(
            [result.scenario_id for result in accepted],
            ["long_pass", "short_pass"],
        )

    def test_failure_fixtures_never_create_trade_plan(self) -> None:
        results = self.run_all()

        failures = [
            result
            for result in results
            if result.scenario_id not in {"long_pass", "short_pass"}
        ]
        self.assertTrue(all(result.decision.plan is None for result in failures))
        self.assertTrue(all(result.execution is None for result in failures))

    def test_repeated_reports_are_byte_identical(self) -> None:
        first = replay_report_json(build_replay_report(self.run_all()))
        second = replay_report_json(build_replay_report(self.run_all()))

        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        parsed = loads(first)
        self.assertEqual(parsed["payload"]["schema_version"], "catalyst.replay.v1")
        self.assertEqual(len(parsed["report_hash"]), 64)

    def test_replay_does_not_fabricate_account_snapshot_freshness(self) -> None:
        fixture = load_replay_fixture(DATA / "long_pass.json")
        stale_account = replace(
            fixture.scenario.account,
            timestamp=fixture.scenario.account.timestamp - timedelta(seconds=3),
        )
        stale_fixture = replace(
            fixture,
            scenario=replace(fixture.scenario, account=stale_account),
        )

        result = ReplayRunner().run(stale_fixture)

        self.assertEqual(result.decision.code.value, "ACCOUNT_SNAPSHOT_STALE")
        self.assertIsNone(result.decision.plan)
