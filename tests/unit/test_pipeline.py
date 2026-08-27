from dataclasses import replace
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import AccountMode, Direction, ReasonCode, SystemState
from catalyst.engine.pipeline import DecisionPipeline
from tests.fixtures import READY_TIME, broker_contract, demo_account, event, long_market


class DecisionPipelineTests(TestCase):
    def setUp(self) -> None:
        self.pipeline = DecisionPipeline()

    def test_builds_long_trade_plan(self) -> None:
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        self.assertEqual(decision.state, SystemState.READY)
        self.assertIsNotNone(decision.plan)
        assert decision.plan is not None
        self.assertEqual(decision.plan.direction, Direction.LONG)
        self.assertEqual(decision.plan.entry, Decimal("101.2"))
        self.assertEqual(decision.plan.stop, Decimal("99.7"))
        self.assertEqual(decision.plan.risk_amount, Decimal("50.0000"))
        self.assertEqual(decision.plan.quantity, Decimal("3.3"))
        self.assertEqual(decision.plan.maximum_loss, Decimal("49.566"))
        self.assertEqual(decision.plan.configuration_hash, decision.configuration_hash)
        self.assertEqual(decision.code, ReasonCode.TRADE_PLAN_READY)

    def test_rejects_non_demo_before_plan(self) -> None:
        account = replace(demo_account(), mode=AccountMode.REAL)
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            account,
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        self.assertEqual(decision.state, SystemState.LOCKED)
        self.assertIsNone(decision.plan)
        self.assertEqual(decision.risk.code, "DEMO_ONLY")
        self.assertEqual(decision.code, ReasonCode.DEMO_ONLY)

    def test_rejects_unconfirmed_setup(self) -> None:
        market = replace(long_market(), cross_asset_confirmations=1)
        decision = self.pipeline.evaluate(
            event(),
            market,
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        self.assertEqual(decision.state, SystemState.WAITING_RETEST)
        self.assertIsNone(decision.plan)
        self.assertEqual(decision.risk.code, "SETUP_NOT_READY")
        self.assertEqual(decision.code, ReasonCode.CONFIRMATION_INSUFFICIENT)

    def test_manual_disarm_prevents_plan(self) -> None:
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=False,
        )
        self.assertEqual(decision.state, SystemState.DISARMED)
        self.assertIsNone(decision.plan)
        self.assertEqual(decision.code, ReasonCode.STATE_DISARMED)

    def test_decision_id_is_deterministic(self) -> None:
        first = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        second = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        assert first.plan is not None and second.plan is not None
        self.assertEqual(first.plan.decision_id, second.plan.decision_id)

    def test_default_pipeline_is_disarmed(self) -> None:
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
        )
        self.assertEqual(decision.state, SystemState.DISARMED)
        self.assertIsNone(decision.plan)

    def test_rejects_contract_for_another_symbol(self) -> None:
        contract = replace(broker_contract(), symbol="US500")
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=contract,
            auto_demo_armed=True,
        )
        self.assertEqual(decision.state, SystemState.LOCKED)
        self.assertEqual(decision.code, ReasonCode.PLAN_INVALID)
        self.assertIn("symbol", decision.reason)

    def test_rejects_contract_for_another_account_currency(self) -> None:
        contract = replace(
            broker_contract(),
            account_currency="EUR",
            profit_currency="USD",
            profit_to_account_rate=Decimal("0.9"),
        )
        decision = self.pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=contract,
            auto_demo_armed=True,
        )
        self.assertEqual(decision.code, ReasonCode.PLAN_INVALID)
        self.assertIn("account currency", decision.reason)
