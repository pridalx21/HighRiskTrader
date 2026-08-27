from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest import TestCase

from catalyst.adapters.fake_broker import FakeDemoBroker
from catalyst.domain.enums import AccountMode, ReasonCode
from catalyst.engine.pipeline import DecisionPipeline
from tests.fixtures import READY_TIME, broker_contract, demo_account, event, long_market


class DemoPipelineIntegrationTests(TestCase):
    def test_synthetic_event_reaches_fake_demo_bracket(self) -> None:
        account = demo_account()
        decision = DecisionPipeline().evaluate(
            event(),
            long_market(),
            account,
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        assert decision.plan is not None
        broker = FakeDemoBroker(account, (broker_contract(),))

        receipt = broker.submit_bracket(decision.plan)

        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.code, "ACCEPTED")
        self.assertEqual(len(broker.orders), 1)

    def test_duplicate_intent_from_later_evaluation_is_rejected(self) -> None:
        account = demo_account()
        pipeline = DecisionPipeline()
        first_decision = pipeline.evaluate(
            event(),
            long_market(),
            account,
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        second_decision = pipeline.evaluate(
            event(),
            replace(
                long_market(),
                timestamp=READY_TIME + timedelta(milliseconds=800),
            ),
            account,
            READY_TIME + timedelta(seconds=1),
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        assert first_decision.plan is not None and second_decision.plan is not None
        broker = FakeDemoBroker(account, (broker_contract(),))
        broker.submit_bracket(first_decision.plan)

        duplicate = broker.submit_bracket(second_decision.plan)

        self.assertEqual(first_decision.plan.decision_id, second_decision.plan.decision_id)
        self.assertFalse(duplicate.accepted)
        self.assertEqual(duplicate.code, "DUPLICATE_ORDER")
        self.assertEqual(len(broker.orders), 1)

    def test_fake_broker_rejects_plan_when_account_mode_is_real(self) -> None:
        demo = demo_account()
        decision = DecisionPipeline().evaluate(
            event(),
            long_market(),
            demo,
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        assert decision.plan is not None
        real_account = replace(demo, mode=AccountMode.REAL)
        broker = FakeDemoBroker(real_account, (broker_contract(),))

        receipt = broker.submit_bracket(decision.plan)

        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, "DEMO_ONLY")

    def test_fake_broker_exposes_explicit_contract_metadata(self) -> None:
        contract = broker_contract()
        broker = FakeDemoBroker(demo_account(), (contract,))
        self.assertEqual(broker.contract_for("US100"), contract)
        with self.assertRaisesRegex(LookupError, "no broker contract"):
            broker.contract_for("UNKNOWN")

    def test_fake_broker_requires_contract_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit contract metadata"):
            FakeDemoBroker(demo_account(), ())

    def test_fake_broker_rejects_quantity_off_volume_step(self) -> None:
        account = demo_account()
        contract = broker_contract()
        decision = DecisionPipeline().evaluate(
            event(),
            long_market(),
            account,
            READY_TIME,
            contract=contract,
            auto_demo_armed=True,
        )
        assert decision.plan is not None
        invalid_plan = replace(decision.plan, quantity=Decimal("3.35"))
        receipt = FakeDemoBroker(account, (contract,)).submit_bracket(invalid_plan)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, "VOLUME_INVALID")

    def test_pipeline_fail_closed_cases_never_reach_broker(self) -> None:
        stale_market = replace(
            long_market(),
            timestamp=READY_TIME - timedelta(seconds=3),
            data_age_seconds=Decimal("3"),
        )
        cases = (
            (stale_market, demo_account(), ReasonCode.DATA_STALE),
            (
                replace(long_market(), ask=Decimal("101.4")),
                demo_account(),
                ReasonCode.SPREAD_TOO_WIDE,
            ),
            (
                replace(long_market(), stop_candidate=Decimal("102")),
                demo_account(),
                ReasonCode.STOP_INVALID,
            ),
            (
                long_market(),
                replace(demo_account(), connected=False),
                ReasonCode.BROKER_DISCONNECTED,
            ),
            (
                long_market(),
                replace(demo_account(), daily_realized_pnl=Decimal("-150")),
                ReasonCode.DAILY_LOSS_LOCK,
            ),
            (
                long_market(),
                replace(demo_account(), active_risk_clusters=1),
                ReasonCode.CLUSTER_LIMIT,
            ),
        )
        for market, account, expected_code in cases:
            with self.subTest(code=expected_code):
                broker = FakeDemoBroker(account, (broker_contract(),))
                decision = DecisionPipeline().evaluate(
                    event(),
                    market,
                    broker.account_snapshot(),
                    READY_TIME,
                    contract=broker.contract_for("US100"),
                    auto_demo_armed=True,
                )
                self.assertIsNone(decision.plan)
                self.assertEqual(decision.code, expected_code)
                self.assertEqual(broker.orders, ())
