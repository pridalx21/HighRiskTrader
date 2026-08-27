"""Deterministic, broker-free vertical-slice demonstration."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from catalyst.adapters.fake_broker import FakeDemoBroker
from catalyst.config import load_runtime_config
from catalyst.domain.enums import AccountMode, EventImportance, EventStatus
from catalyst.domain.models import AccountSnapshot, BrokerContract, EconomicEvent, MarketSnapshot
from catalyst.engine.pipeline import DecisionPipeline


def build_demo_inputs() -> tuple[
    EconomicEvent,
    MarketSnapshot,
    AccountSnapshot,
    BrokerContract,
    datetime,
]:
    event_time = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)
    now = event_time + timedelta(minutes=3)
    event = EconomicEvent(
        event_id="SYNTH_US_CPI_001",
        name="Synthetic US CPI",
        scheduled_at=event_time,
        ingested_at=event_time - timedelta(days=1),
        currency="USD",
        importance=EventImportance.HIGH,
        status=EventStatus.SCHEDULED,
        eligible_symbols=("US100",),
        source="synthetic_demo",
    )
    market = MarketSnapshot(
        symbol="US100",
        timestamp=now - timedelta(milliseconds=300),
        bid=Decimal("20101.0"),
        ask=Decimal("20102.0"),
        pre_event_high=Decimal("20090.0"),
        pre_event_low=Decimal("19980.0"),
        atr=Decimal("35.0"),
        baseline_spread=Decimal("0.8"),
        data_age_seconds=Decimal("0.3"),
        retest_holds=True,
        stop_candidate=Decimal("20084.0"),
        related_markets_observed=3,
        cross_asset_confirmations=2,
        market_open=True,
    )
    account = AccountSnapshot(
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
        timestamp=now,
    )
    contract = BrokerContract(
        symbol="US100",
        tick_size=Decimal("0.1"),
        tick_value=Decimal("1"),
        contract_size=Decimal("1"),
        profit_currency="CHF",
        account_currency="CHF",
        profit_to_account_rate=Decimal("1"),
        volume_minimum=Decimal("0.01"),
        volume_maximum=Decimal("10"),
        volume_step=Decimal("0.01"),
        commission_per_volume=Decimal("1"),
        slippage_ticks=Decimal("1"),
    )
    return event, market, account, contract, now


def main() -> None:
    event, market, account, contract, now = build_demo_inputs()
    project_root = Path(__file__).resolve().parents[2]
    config = load_runtime_config(project_root / "config" / "settings.example.toml")
    pipeline = DecisionPipeline(config)
    broker = FakeDemoBroker(account, (contract,))
    decision = pipeline.evaluate(
        event,
        market,
        account,
        now,
        contract=broker.contract_for(market.symbol),
        auto_demo_armed=True,
    )
    if decision.plan is None:
        raise SystemExit(f"unexpected demo rejection: {decision.reason}")

    receipt = broker.submit_bracket(decision.plan)
    if not receipt.accepted:
        raise SystemExit(f"unexpected fake-broker rejection: {receipt.code}")

    print("CATALYST deterministic demo")
    print(f"state={decision.state.value}")
    print(f"event={event.event_id}")
    print(f"direction={decision.plan.direction.value}")
    print(f"entry={decision.plan.entry}")
    print(f"stop={decision.plan.stop}")
    print(f"risk_chf={decision.plan.risk_amount}")
    print(f"maximum_loss_chf={decision.plan.maximum_loss}")
    print(f"quantity_demo={decision.plan.quantity}")
    print(f"configuration_hash={decision.configuration_hash}")
    print(f"broker_receipt={receipt.code}")
    print("warning=synthetic contract metadata is not broker-ready MT5 metadata")


if __name__ == "__main__":
    main()
