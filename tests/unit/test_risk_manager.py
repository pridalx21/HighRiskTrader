from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import AccountMode
from catalyst.risk.manager import RiskManager
from catalyst.risk.policy import RiskPolicy
from tests.fixtures import READY_TIME, broker_contract, demo_account


class RiskManagerTests(TestCase):
    def setUp(self) -> None:
        self.manager = RiskManager()

    def assess(self, account):
        return self.manager.assess(account, READY_TIME, Decimal("2.0"))

    def test_allows_five_percent_risk_on_clean_demo_account(self) -> None:
        decision = self.assess(demo_account())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk_amount, Decimal("50.0000"))

    def test_rejects_real_account(self) -> None:
        decision = self.assess(replace(demo_account(), mode=AccountMode.REAL))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "DEMO_ONLY")

    def test_rejects_unknown_account(self) -> None:
        decision = self.assess(replace(demo_account(), mode=AccountMode.UNKNOWN))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "DEMO_ONLY")

    def test_rejects_disconnected_account(self) -> None:
        decision = self.assess(replace(demo_account(), connected=False))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "BROKER_DISCONNECTED")

    def test_rejects_stale_account_snapshot(self) -> None:
        decision = self.assess(replace(demo_account(), timestamp=READY_TIME - timedelta(seconds=3)))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "ACCOUNT_SNAPSHOT_STALE")

    def test_rejects_future_account_snapshot(self) -> None:
        decision = self.assess(
            replace(demo_account(), timestamp=READY_TIME + timedelta(microseconds=1))
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "ACCOUNT_SNAPSHOT_STALE")

    def test_daily_loss_limit_locks_at_three_day_start_r(self) -> None:
        decision = self.assess(replace(demo_account(), daily_realized_pnl=Decimal("-150.00")))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "DAILY_LOSS_LOCK")

    def test_open_worst_case_risk_counts_toward_daily_lock(self) -> None:
        decision = self.assess(replace(demo_account(), open_worst_case_risk=Decimal("150.00")))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "DAILY_LOSS_LOCK")

    def test_loss_streak_locks(self) -> None:
        decision = self.assess(replace(demo_account(), consecutive_losses=3))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "LOSS_STREAK_LOCK")

    def test_active_cluster_locks(self) -> None:
        decision = self.assess(replace(demo_account(), active_risk_clusters=1))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "CLUSTER_LIMIT")

    def test_position_size_rounds_down_and_includes_cost_allowance(self) -> None:
        sizing = self.manager.size_position(
            Decimal("50"), Decimal("101.2"), Decimal("99.7"), broker_contract()
        )
        self.assertEqual(sizing.quantity, Decimal("3.3"))
        self.assertEqual(sizing.maximum_loss, Decimal("49.566"))

    def test_position_size_rejects_zero_stop_distance(self) -> None:
        with self.assertRaisesRegex(ValueError, "must differ"):
            self.manager.size_position(
                Decimal("50"), Decimal("100"), Decimal("100"), broker_contract()
            )

    def test_position_size_accepts_exact_step_with_cost_headroom(self) -> None:
        sizing = self.manager.size_position(
            Decimal("45.10"), Decimal("101.2"), Decimal("99.7"), broker_contract()
        )
        self.assertEqual(sizing.quantity, Decimal("3.0"))
        self.assertEqual(sizing.maximum_loss, Decimal("45.060"))

    def test_position_size_accepts_minimum_boundary(self) -> None:
        sizing = self.manager.size_position(
            Decimal("1.51"), Decimal("101.2"), Decimal("99.7"), broker_contract()
        )
        self.assertEqual(sizing.quantity, Decimal("0.1"))
        self.assertEqual(sizing.maximum_loss, Decimal("1.502"))

    def test_position_size_rejects_below_minimum(self) -> None:
        with self.assertRaisesRegex(ValueError, "below volume_minimum"):
            self.manager.size_position(
                Decimal("1.49"),
                Decimal("101.2"),
                Decimal("99.7"),
                broker_contract(),
            )

    def test_position_size_rejects_raw_quantity_above_maximum(self) -> None:
        contract = replace(broker_contract(), volume_maximum=Decimal("3.0"))
        with self.assertRaisesRegex(ValueError, "exceeds volume_maximum"):
            self.manager.size_position(
                Decimal("45.10"), Decimal("101.2"), Decimal("99.7"), contract
            )

    def test_position_size_rejects_post_cost_maximum_loss(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds permitted risk"):
            self.manager.size_position(
                Decimal("45.00"),
                Decimal("101.2"),
                Decimal("99.7"),
                broker_contract(),
            )

    def test_position_size_applies_profit_currency_conversion(self) -> None:
        contract = replace(
            broker_contract(),
            profit_currency="USD",
            profit_to_account_rate=Decimal("0.9"),
        )
        sizing = self.manager.size_position(
            Decimal("50.10"), Decimal("101.2"), Decimal("99.7"), contract
        )
        self.assertEqual(sizing.quantity, Decimal("3.7"))
        self.assertEqual(sizing.maximum_loss, Decimal("50.0203"))

    def test_position_size_rejects_prices_off_tick_grid(self) -> None:
        with self.assertRaisesRegex(ValueError, "align to tick_size"):
            self.manager.size_position(
                Decimal("50"),
                Decimal("101.21"),
                Decimal("99.7"),
                broker_contract(),
            )

    def test_policy_rejects_risk_fraction_above_approved_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "0.05"):
            RiskPolicy(risk_fraction=Decimal("0.06"))

    def test_policy_rejects_float_risk_fraction(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be Decimal"):
            RiskPolicy(risk_fraction=0.05)

    def test_policy_rejects_daily_limit_above_hard_cap(self) -> None:
        with self.assertRaisesRegex(ValueError, "0, 3"):
            RiskPolicy(maximum_daily_loss_r=Decimal("4"))
