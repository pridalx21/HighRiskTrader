from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from catalyst.adapters.guarded_demo_broker import GuardedDemoBroker
from catalyst.controls import LocalKillSwitch
from catalyst.domain.enums import AccountMode, Direction
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.journal import OrderIntentRecord, OrderIntentState
from catalyst.ports.reconciliation import BrokerOrderLookup, BrokerOrderState

NOW = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)


class FakeDelegate:
    def __init__(self) -> None:
        self._armed = False
        self.submit_calls = 0

    @property
    def armed(self) -> bool:
        return self._armed

    def arm_demo_execution(self) -> None:
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    def account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            mode=AccountMode.DEMO,
            currency="CHF",
            balance=Decimal("1000"),
            equity=Decimal("1000"),
            day_start_equity=Decimal("1000"),
            month_start_equity=Decimal("1000"),
            daily_realized_pnl=Decimal("0"),
            consecutive_losses=0,
            active_risk_clusters=0,
            open_worst_case_risk=Decimal("0"),
            timestamp=NOW,
        )

    def contract_for(self, symbol: str) -> BrokerContract:
        return BrokerContract(
            symbol=symbol,
            tick_size=Decimal("0.1"),
            tick_value=Decimal("0.1"),
            contract_size=Decimal("1"),
            profit_currency="CHF",
            account_currency="CHF",
            profit_to_account_rate=Decimal("1"),
            volume_minimum=Decimal("0.1"),
            volume_maximum=Decimal("10"),
            volume_step=Decimal("0.1"),
            commission_per_volume=Decimal("0"),
            slippage_ticks=Decimal("1"),
        )

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        self.submit_calls += 1
        return OrderReceipt(True, plan.decision_id, "123", "DONE", "accepted")

    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup:
        return BrokerOrderLookup(BrokerOrderState.NOT_FOUND, None, "not found")


def plan() -> TradePlan:
    return TradePlan(
        decision_id="decision-guard",
        event_id="event-guard",
        strategy_id="event-retest-v1",
        symbol="US100",
        direction=Direction.LONG,
        created_at=NOW,
        entry=Decimal("100"),
        stop=Decimal("99"),
        risk_amount=Decimal("50"),
        maximum_loss=Decimal("45"),
        quantity=Decimal("1"),
        configuration_hash="a" * 64,
        rationale=("test",),
    )


class GuardedDemoBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.delegate = FakeDelegate()
        self.kill = LocalKillSwitch(Path(self.temp.name) / "kill.json")
        self.broker = GuardedDemoBroker(self.delegate, self.kill)

    def test_delegate_paths_work_when_latch_clear(self) -> None:
        self.broker.arm_demo_execution()
        self.assertTrue(self.broker.armed)
        self.assertEqual(self.broker.account_snapshot().mode, AccountMode.DEMO)
        self.assertEqual(self.broker.contract_for("US100").symbol, "US100")
        receipt = self.broker.submit_bracket(plan())
        self.assertTrue(receipt.accepted)
        self.assertEqual(self.delegate.submit_calls, 1)
        intent = OrderIntentRecord(
            idempotency_key="decision-guard",
            event_id="event-guard",
            decision_id="decision-guard",
            created_at=NOW,
            plan_json='{"symbol":"US100"}',
            plan_hash="b" * 64,
            latest_state=OrderIntentState.UNCERTAIN,
        )
        self.assertEqual(self.broker.lookup_order(intent).state, BrokerOrderState.NOT_FOUND)

    def test_active_latch_blocks_arm_and_submit_and_disarms_delegate(self) -> None:
        self.delegate._armed = True
        self.kill.engage(occurred_at=NOW, reason="test incident")
        self.assertFalse(self.broker.armed)
        with self.assertRaisesRegex(RuntimeError, "kill switch"):
            self.broker.arm_demo_execution()
        self.assertFalse(self.delegate.armed)
        self.delegate._armed = True
        with self.assertRaisesRegex(RuntimeError, "blocks"):
            self.broker.submit_bracket(plan())
        self.assertFalse(self.delegate.armed)
        self.assertEqual(self.delegate.submit_calls, 0)

    def test_manual_disarm_always_delegates(self) -> None:
        self.delegate._armed = True
        self.broker.disarm()
        self.assertFalse(self.delegate.armed)


if __name__ == "__main__":
    unittest.main()
