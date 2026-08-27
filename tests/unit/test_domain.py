from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import AccountMode
from catalyst.domain.models import AccountSnapshot
from tests.fixtures import EVENT_TIME, broker_contract, long_market


class DomainValidationTests(TestCase):
    def test_market_rejects_naive_timestamp(self) -> None:
        market = long_market()
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            replace(market, timestamp=datetime(2030, 1, 1))

    def test_market_rejects_non_utc_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "normalized to UTC"):
            replace(
                long_market(),
                timestamp=datetime(2030, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            )

    def test_market_rejects_inverted_bid_ask(self) -> None:
        market = long_market()
        with self.assertRaisesRegex(ValueError, "ask"):
            replace(market, bid=Decimal("102"), ask=Decimal("101"))

    def test_market_rejects_float_price(self) -> None:
        with self.assertRaisesRegex(ValueError, "bid must be Decimal"):
            replace(long_market(), bid=101.0)

    def test_market_rejects_impossible_confirmation_count(self) -> None:
        market = long_market()
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            replace(market, related_markets_observed=1, cross_asset_confirmations=2)

    def test_account_rejects_non_positive_equity(self) -> None:
        with self.assertRaisesRegex(ValueError, "equity"):
            AccountSnapshot(
                mode=AccountMode.DEMO,
                currency="CHF",
                balance=Decimal("1000"),
                equity=Decimal("0"),
                day_start_equity=Decimal("1000"),
                month_start_equity=Decimal("1000"),
                daily_realized_pnl=Decimal("0"),
                consecutive_losses=0,
                active_risk_clusters=0,
                open_worst_case_risk=Decimal("0"),
                timestamp=datetime(2030, 1, 1, tzinfo=UTC),
            )

    def test_fixture_timestamp_is_aware(self) -> None:
        self.assertIsNotNone(EVENT_TIME.utcoffset())

    def test_contract_rejects_non_finite_tick_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "tick_value"):
            replace(broker_contract(), tick_value=Decimal("NaN"))

    def test_contract_rejects_unaligned_volume_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "volume_minimum"):
            replace(broker_contract(), volume_minimum=Decimal("0.15"))

    def test_contract_requires_pessimistic_cost_allowance(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowance"):
            replace(
                broker_contract(),
                commission_per_volume=Decimal("0"),
                slippage_ticks=Decimal("0"),
            )

    def test_contract_rejects_unknown_currency(self) -> None:
        with self.assertRaisesRegex(ValueError, "profit_currency must be known"):
            replace(
                broker_contract(),
                profit_currency="UNKNOWN",
                profit_to_account_rate=Decimal("0.9"),
            )
