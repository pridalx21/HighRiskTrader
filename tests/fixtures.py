"""Deterministic domain fixtures shared by unit and integration tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from catalyst.domain.enums import AccountMode, EventImportance, EventStatus
from catalyst.domain.models import AccountSnapshot, BrokerContract, EconomicEvent, MarketSnapshot

EVENT_TIME = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)
READY_TIME = EVENT_TIME + timedelta(minutes=3)


def event() -> EconomicEvent:
    return EconomicEvent(
        event_id="TEST_EVENT",
        name="Synthetic high-impact release",
        scheduled_at=EVENT_TIME,
        ingested_at=EVENT_TIME - timedelta(days=1),
        currency="USD",
        importance=EventImportance.HIGH,
        status=EventStatus.SCHEDULED,
        eligible_symbols=("US100",),
        source="test_fixture",
    )


def long_market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="US100",
        timestamp=READY_TIME - timedelta(milliseconds=200),
        bid=Decimal("101.0"),
        ask=Decimal("101.2"),
        pre_event_high=Decimal("100.0"),
        pre_event_low=Decimal("95.0"),
        atr=Decimal("2.5"),
        baseline_spread=Decimal("0.1"),
        data_age_seconds=Decimal("0.2"),
        retest_holds=True,
        stop_candidate=Decimal("99.7"),
        related_markets_observed=3,
        cross_asset_confirmations=2,
        market_open=True,
    )


def demo_account() -> AccountSnapshot:
    return AccountSnapshot(
        mode=AccountMode.DEMO,
        currency="CHF",
        balance=Decimal("1000.00"),
        equity=Decimal("1000.00"),
        day_start_equity=Decimal("1000.00"),
        month_start_equity=Decimal("1000.00"),
        daily_realized_pnl=Decimal("0.00"),
        consecutive_losses=0,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0.00"),
        timestamp=READY_TIME,
    )


def broker_contract() -> BrokerContract:
    return BrokerContract(
        symbol="US100",
        tick_size=Decimal("0.1"),
        tick_value=Decimal("1"),
        contract_size=Decimal("1"),
        profit_currency="CHF",
        account_currency="CHF",
        profit_to_account_rate=Decimal("1"),
        volume_minimum=Decimal("0.1"),
        volume_maximum=Decimal("100"),
        volume_step=Decimal("0.1"),
        commission_per_volume=Decimal("0.01"),
        slippage_ticks=Decimal("0.01"),
    )
