from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from catalyst.domain.serialization import canonical_json
from catalyst.validation import (
    ValidationConfig,
    ValidationObservation,
    load_observations_json,
    run_validation,
    validation_markdown,
    write_evidence_pack,
)

START = datetime(2025, 1, 1, 13, 30, tzinfo=UTC)


def observation(
    index: int,
    value: Decimal | None,
    *,
    source: str = "historical",
    excluded_reason: str | None = None,
) -> ValidationObservation:
    return ValidationObservation(
        observation_id=f"OBS-{index:04d}-{source}",
        occurred_at=START + timedelta(days=index),
        event_family="CPI" if index % 2 == 0 else "NFP",
        instrument="US100" if index % 3 else "XAUUSD",
        regime="high_vol" if index % 4 else "normal",
        source=source,
        qualified=True,
        traded=value is not None,
        r_after_costs=value,
        intended_slippage_r=Decimal("0.03") if source == "demo" else None,
        actual_slippage_r=Decimal("0.04") if source == "demo" else None,
        excluded_reason=excluded_reason,
    )


class ValidationTests(unittest.TestCase):
    def test_small_sample_is_revise_and_reproducible(self) -> None:
        historical = tuple(
            observation(index, Decimal("1") if index % 3 else Decimal("-0.5"))
            for index in range(30)
        )
        demo = tuple(observation(1000 + index, Decimal("0.5"), source="demo") for index in range(3))
        rows = historical + demo
        config = ValidationConfig(
            strategy_version="event-retest-v1",
            bootstrap_iterations=25,
            unattended_demo_weeks=Decimal("2"),
        )
        first = run_validation(rows, config)
        second = run_validation(tuple(reversed(rows)), config)
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(first["verdict"], "REVISE")
        self.assertGreater(len(first["walk_forward"]), 0)
        self.assertIn("wider_spread_commission_slippage", first["stress_scenarios"])
        self.assertEqual(first["bootstrap_monte_carlo"]["iterations"], 25)
        self.assertEqual(first["demo_vs_replay"]["comparable_orders"], 3)
        self.assertIn("CPI", first["event_family_holdouts"])
        self.assertIn("US100", first["instrument_holdouts"])
        self.assertIn("2025", first["year_breakdown"])
        self.assertIn("Verdict: **REVISE**", validation_markdown(first))

    def test_strong_distributed_evidence_can_continue(self) -> None:
        historical = tuple(
            observation(index, Decimal("-0.2") if index % 3 == 0 else Decimal("0.8"))
            for index in range(360)
        )
        demo = tuple(
            observation(
                1000 + index,
                Decimal("-0.1") if index % 3 == 0 else Decimal("0.4"),
                source="demo",
            )
            for index in range(12)
        )
        config = ValidationConfig(
            strategy_version="event-retest-v1-frozen",
            bootstrap_iterations=20,
            unattended_demo_weeks=Decimal("8"),
        )
        report = run_validation(historical + demo, config)
        self.assertEqual(report["verdict"], "CONTINUE")
        self.assertGreaterEqual(report["evaluation"]["trade_count"], 100)
        self.assertGreater(report["evaluation"]["profit_factor"], Decimal("1.20"))
        self.assertEqual(report["verdict_reasons"], ())

    def test_large_negative_evaluation_stops(self) -> None:
        historical = tuple(
            observation(index, Decimal("0.1") if index < 250 else Decimal("-0.6"))
            for index in range(360)
        )
        demo = tuple(
            observation(1000 + index, Decimal("-0.1"), source="demo") for index in range(10)
        )
        config = ValidationConfig(
            strategy_version="losing-frozen",
            bootstrap_iterations=10,
            unattended_demo_weeks=Decimal("8"),
        )
        report = run_validation(historical + demo, config)
        self.assertEqual(report["verdict"], "STOP")
        self.assertLessEqual(report["evaluation"]["expectancy_r"], Decimal("0"))

    def test_exclusions_are_preserved(self) -> None:
        rows = (
            observation(0, Decimal("1")),
            observation(1, None, excluded_reason="calendar timestamp ambiguous"),
            observation(2, Decimal("-0.5")),
        )
        report = run_validation(
            rows,
            ValidationConfig(strategy_version="v1", bootstrap_iterations=5),
        )
        self.assertEqual(len(report["excluded_observations"]), 1)
        self.assertEqual(
            report["excluded_observations"][0]["reason"],
            "calendar timestamp ambiguous",
        )

    def test_evidence_pack_writes_hashed_machine_and_markdown_outputs(self) -> None:
        rows = tuple(observation(index, Decimal("0.5")) for index in range(12))
        config = ValidationConfig(strategy_version="v1", bootstrap_iterations=5)
        with tempfile.TemporaryDirectory() as directory:
            manifest = write_evidence_pack(rows, config, directory)
            output = Path(directory)
            self.assertTrue((output / "validation_report.json").exists())
            self.assertTrue((output / "validation_report.md").exists())
            self.assertTrue((output / "manifest.json").exists())
            self.assertEqual(len(manifest["input_hash"]), 64)
            report_text = (output / "validation_report.json").read_text(encoding="utf-8")
            parsed = json.loads(report_text)
            self.assertEqual(parsed["verdict"], "REVISE")

    def test_json_loader_is_strict_about_duplicates_shape_and_booleans(self) -> None:
        payload = [
            {
                "observation_id": "A",
                "occurred_at": "2030-01-01T00:00:00Z",
                "event_family": "CPI",
                "instrument": "US100",
                "regime": "normal",
                "source": "historical",
                "qualified": True,
                "traded": True,
                "r_after_costs": "0.5",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_observations_json(path)
            self.assertEqual(loaded[0].r_after_costs, Decimal("0.5"))
            path.write_text(json.dumps(payload + payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_observations_json(path)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_observations_json(path)
            invalid_boolean = [dict(payload[0], qualified="true")]
            path.write_text(json.dumps(invalid_boolean), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_observations_json(path)

    def test_invalid_observations_and_config_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ValidationObservation(
                observation_id="bad",
                occurred_at=datetime(2030, 1, 1),
                event_family="CPI",
                instrument="US100",
                regime="normal",
                source="historical",
                qualified=True,
                traded=True,
                r_after_costs=Decimal("1"),
            )
        with self.assertRaises(ValueError):
            ValidationObservation(
                observation_id="bad2",
                occurred_at=START,
                event_family="CPI",
                instrument="US100",
                regime="normal",
                source="other",
                qualified=True,
                traded=False,
                r_after_costs=None,
            )
        with self.assertRaises(ValueError):
            ValidationConfig(strategy_version="", bootstrap_iterations=1)
        with self.assertRaises(ValueError):
            ValidationConfig(
                strategy_version="v1",
                evaluation_fraction=Decimal("1"),
            )
        with self.assertRaises(ValueError):
            run_validation((), ValidationConfig(strategy_version="v1"))


if __name__ == "__main__":
    unittest.main()
