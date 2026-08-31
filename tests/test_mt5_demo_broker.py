from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest

from catalyst.adapters.mt5_broker import (
    MT5AccountRiskState,
    MT5DemoBroker,
    MT5DemoConfig,
    MT5SymbolEconomics,
)
from catalyst.domain.enums import Direction
from catalyst.domain.models import TradePlan
from catalyst.ports.journal import OrderIntentRecord, OrderIntentState
from catalyst.ports.reconciliation import BrokerOrderState


NOW = datetime(2030, 1, 10, 13, 32, tzinfo=UTC)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008

    def __init__(self, *, trade_mode: int = ACCOUNT_TRADE_MODE_DEMO) -> None:
        self.trade_mode = trade_mode
        self.initialized = 0
        self.logged_in = 0
        self.shutdowns = 0
        self.sent_requests: list[dict[str, object]] = []
        self.check_retcode = 0
        self.send_result: object | None = SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=12345,
            comment="done",
        )
        self.open_orders: tuple[object, ...] | None = ()
        self.history_orders: tuple[object, ...] | None = ()

    def initialize(self, *, path: str) -> bool:
        self.initialized += 1
        return bool(path)

    def login(self, login: int, *, server: str) -> bool:
        self.logged_in += 1
        return login == 123456 and server == "Demo-Server"

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def shutdown(self) -> None:
        self.shutdowns += 1

    def terminal_info(self) -> object:
        return SimpleNamespace(connected=True)

    def account_info(self) -> object:
        return SimpleNamespace(
            login=123456,
            server="Demo-Server",
            trade_mode=self.trade_mode,
            currency="CHF",
            balance=1000.0,
            equity=995.0,
        )

    def symbol_info(self, symbol: str) -> object | None:
        if symbol != "USTEC.cash":
            return None
        return SimpleNamespace(
            trade_tick_size=0.1,
            trade_tick_value=0.1,
            trade_contract_size=1.0,
            currency_profit="CHF",
            volume_min=0.1,
            volume_max=10.0,
            volume_step=0.1,
        )

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        return symbol == "USTEC.cash" and selected

    def order_check(self, request: dict[str, object]) -> object:
        return SimpleNamespace(retcode=self.check_retcode, comment="check")

    def order_send(self, request: dict[str, object]) -> object | None:
        self.sent_requests.append(request)
        return self.send_result

    def orders_get(self, *, symbol: str) -> tuple[object, ...] | None:
        assert symbol == "USTEC.cash"
        return self.open_orders

    def history_orders_get(self, start: datetime, end: datetime) -> tuple[object, ...] | None:
        assert start < end
        return self.history_orders


def config(*, auto_execution_enabled: bool = False) -> MT5DemoConfig:
    return MT5DemoConfig(
        terminal_path=Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
        login=123456,
        server="Demo-Server",
        symbol_mapping={"US100": "USTEC.cash"},
        symbol_economics={
            "US100": MT5SymbolEconomics(
                commission_per_volume=Decimal("0"),
                slippage_ticks=Decimal("2"),
                profit_to_account_rate=Decimal("1"),
            )
        },
        auto_execution_enabled=auto_execution_enabled,
        reconnect_delay_seconds=Decimal("0"),
    )


def risk_state() -> MT5AccountRiskState:
    return MT5AccountRiskState(
        day_start_equity=Decimal("1000"),
        month_start_equity=Decimal("1000"),
        daily_realized_pnl=Decimal("-5"),
        consecutive_losses=1,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0"),
    )


def plan() -> TradePlan:
    return TradePlan(
        decision_id="decision-001",
        event_id="event-001",
        strategy_id="event-reaction-retest-v1",
        symbol="US100",
        direction=Direction.LONG,
        created_at=NOW,
        entry=Decimal("100.0"),
        stop=Decimal("99.0"),
        risk_amount=Decimal("50"),
        maximum_loss=Decimal("45"),
        quantity=Decimal("1.0"),
        configuration_hash="a" * 64,
        rationale=("test",),
    )


class MT5DemoBrokerTests(unittest.TestCase):
    def broker(self, api: FakeMT5, *, auto: bool = False) -> MT5DemoBroker:
        return MT5DemoBroker(
            config(auto_execution_enabled=auto),
            risk_state,
            mt5_module=api,
            clock=lambda: NOW,
            sleeper=lambda _: None,
        )

    def test_real_account_fails_closed(self) -> None:
        broker = self.broker(FakeMT5(trade_mode=FakeMT5.ACCOUNT_TRADE_MODE_REAL))
        with self.assertRaisesRegex(RuntimeError, "not positively identified as demo"):
            broker.connect()
        self.assertFalse(broker.armed)

    def test_shadow_snapshot_and_contract_are_normalized(self) -> None:
        api = FakeMT5()
        broker = self.broker(api)
        snapshot = broker.account_snapshot()
        contract = broker.contract_for("US100")
        self.assertEqual(snapshot.balance, Decimal("1000.0"))
        self.assertEqual(snapshot.equity, Decimal("995.0"))
        self.assertEqual(snapshot.day_start_equity, Decimal("1000"))
        self.assertTrue(snapshot.connected)
        self.assertEqual(contract.symbol, "US100")
        self.assertEqual(contract.volume_step, Decimal("0.1"))
        self.assertEqual(api.sent_requests, [])

    def test_automatic_order_requires_config_and_explicit_arm(self) -> None:
        api = FakeMT5()
        broker = self.broker(api)
        with self.assertRaisesRegex(RuntimeError, "not explicitly armed"):
            broker.submit_bracket(plan())
        with self.assertRaisesRegex(RuntimeError, "disabled by configuration"):
            broker.arm_demo_execution()
        self.assertEqual(api.sent_requests, [])

    def test_armed_demo_submit_has_initial_stop_and_only_one_send(self) -> None:
        api = FakeMT5()
        api.check_retcode = 0
        broker = self.broker(api, auto=True)
        broker.arm_demo_execution()
        receipt = broker.submit_bracket(plan())
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.broker_order_id, "12345")
        self.assertEqual(len(api.sent_requests), 1)
        request = api.sent_requests[0]
        self.assertEqual(request["symbol"], "USTEC.cash")
        self.assertEqual(request["sl"], 99.0)
        self.assertEqual(request["comment"], broker._comment("decision-001"))

    def test_ambiguous_send_result_raises_timeout_without_retry(self) -> None:
        api = FakeMT5()
        api.check_retcode = 0
        api.send_result = None
        broker = self.broker(api, auto=True)
        broker.arm_demo_execution()
        with self.assertRaises(TimeoutError):
            broker.submit_bracket(plan())
        self.assertEqual(len(api.sent_requests), 1)

    def test_order_check_rejection_never_calls_order_send(self) -> None:
        api = FakeMT5()
        api.check_retcode = 10013
        broker = self.broker(api, auto=True)
        broker.arm_demo_execution()
        receipt = broker.submit_bracket(plan())
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, "MT5_CHECK_10013")
        self.assertEqual(api.sent_requests, [])

    def test_reconciliation_finds_open_order_without_arming(self) -> None:
        api = FakeMT5()
        broker = self.broker(api, auto=True)
        token = broker._comment("decision-001")
        api.open_orders = (SimpleNamespace(ticket=555, comment=token),)
        intent = OrderIntentRecord(
            idempotency_key="decision-001",
            event_id="event-001",
            decision_id="decision-001",
            created_at=NOW,
            plan_json='{"symbol":"US100"}',
            plan_hash="b" * 64,
            latest_state=OrderIntentState.UNCERTAIN,
        )
        lookup = broker.lookup_order(intent)
        self.assertEqual(lookup.state, BrokerOrderState.FOUND_OPEN)
        self.assertEqual(lookup.broker_order_id, "555")
        self.assertFalse(broker.armed)
        self.assertEqual(api.sent_requests, [])


if __name__ == "__main__":
    unittest.main()
