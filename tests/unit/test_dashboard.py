from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from catalyst.dashboard import AccountView, DashboardSnapshot, GateView, PlanView
from catalyst.domain.enums import SystemState

NOW = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)


class DashboardSnapshotTests(unittest.TestCase):
    def snapshot(self, **overrides: object) -> DashboardSnapshot:
        values: dict[str, object] = {
            "generated_at": NOW,
            "source_at": NOW,
            "next_event": "Synthetic CPI",
            "affected_markets": ("US100", "XAUUSD"),
            "state": SystemState.READY,
            "gates": (
                GateView("catalyst", True, "CATALYST_PASS", "high-impact event"),
                GateView("acceptance", True, "ACCEPTANCE_PASS", "breakout accepted"),
                GateView("confirmation", True, "CONFIRMATION_PASS", "cross-asset confirmed"),
                GateView("execution", True, "EXECUTION_PASS", "execution conditions valid"),
            ),
            "plan": PlanView(
                "long",
                Decimal("100.2"),
                Decimal("99.2"),
                Decimal("0.1"),
                Decimal("50"),
            ),
            "account": AccountView(
                Decimal("1000"),
                Decimal("1010"),
                Decimal("10"),
                Decimal("0.2"),
                Decimal("50"),
                (),
            ),
            "orders": (),
            "positions": (),
            "recent_decisions": ("TRADE_PLAN_READY",),
        }
        values.update(overrides)
        return DashboardSnapshot(**values)  # type: ignore[arg-type]

    def test_freshness_is_explicit(self) -> None:
        snapshot = self.snapshot()
        self.assertFalse(snapshot.is_stale(NOW + timedelta(seconds=4)))
        self.assertTrue(snapshot.is_stale(NOW + timedelta(seconds=6)))
        self.assertTrue(snapshot.is_stale(NOW - timedelta(seconds=1)))

    def test_dashboard_contains_read_only_plan_view(self) -> None:
        snapshot = self.snapshot()
        self.assertEqual(snapshot.plan.maximum_planned_loss_chf, Decimal("50"))
        with self.assertRaises(AttributeError):
            snapshot.plan.entry = Decimal("1")  # type: ignore[misc]

    def test_replay_download_requires_name(self) -> None:
        with self.assertRaises(ValueError):
            self.snapshot(replay_report_bytes=b"{}")
        snapshot = self.snapshot(replay_report_name="replay.json", replay_report_bytes=b"{}")
        self.assertEqual(snapshot.replay_report_name, "replay.json")

    def test_more_than_four_gates_is_rejected(self) -> None:
        gates = tuple(GateView(str(index), True, "PASS", "reason") for index in range(5))
        with self.assertRaises(ValueError):
            self.snapshot(gates=gates)

    def test_invalid_gate_text_and_naive_time_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GateView("", True, "PASS", "reason")
        with self.assertRaises(ValueError):
            self.snapshot(generated_at=datetime(2030, 1, 1))


if __name__ == "__main__":
    unittest.main()
