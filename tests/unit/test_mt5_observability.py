from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from catalyst.adapters.mt5_broker import (
    MT5AccountRiskState,
    MT5DemoBroker,
    MT5DemoConfig,
    MT5SymbolEconomics,
)
from catalyst.adapters.mt5_observability import MT5ReadAdapter
from catalyst.domain.enums import Direction
from catalyst.domain.models import TradePlan

NOW = datetime(2030, 1, 10, 13, 32, tzinfo=UTC)


class FakeReadMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    COPY_TICKS_ALL = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5

    def __init__(self) -> None:
        self.tick_rows: tuple[object, ...] | None = ()
        self.position_rows: tuple[object, ...] | None = ()
        self.order_rows: tuple[object, ...] | None = ()
        self.deal_rows: tuple[object, ...] | None = ()
        self.latest = SimpleNamespace(
            time_msc=int(NOW.timestamp() * 1000), bid=100.0, ask=100.2
        )

    def initialize(self, *, path: str) -> bool:
        return bool(path)

    def login(self, login: int, *, server: str) -> bool:
        return login == 123456 and server == "Demo-Server"

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def shutdown(self) -> None:
        return None

    def terminal_info(self) -> object:
        return SimpleNamespace(connected=True)

    def account_info(self) -> object:
        return SimpleNamespace(
            login=123456,
            server="Demo-Server",
            trade_mode=self.ACCOUNT_TRADE_MODE_DEMO,
            currency="CHF",
            balance=1000.0,
            equity=1000.0,
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

    def copy_ticks_range(
        self, symbol: str, start: datetime, end: datetime, flags: int
    ) -> tuple[object, ...] | None:
        self.assert_symbol(symbol)
        assert start < end
        assert flags == self.COPY_TICKS_ALL
        return self.tick_rows

    def symbol_info_tick(self, symbol: str) -> object | None:
        self.assert_symbol(symbol)
        return self.latest

    def positions_get(self) -> tuple[object, ...] | None:
        return self.position_rows

    def orders_get(self) -> tuple[object, ...] | None:
        return self.order_rows

    def history_deals_get(
        self, start: datetime, end: datetime
    ) -> tuple[object, ...] | None:
        assert start < end
        return self.deal_rows

    @staticmethod
    def assert_symbol(symbol: str) -> None:
        assert symbol == "USTEC.cash"


def risk_state() -> MT5AccountRiskState:
    return MT5AccountRiskState(
        day_start_equity=Decimal("1000"),
        month_start_equity=Decimal("1000"),
        daily_realized_pnl=Decimal("0"),
        consecutive_losses=0,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0"),
    )


def make_broker(api: FakeReadMT5) -> MT5DemoBroker:
    config = MT5DemoConfig(
        terminal_path=Path("C:/MetaTrader5/terminal64.exe"),
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
        reconnect_delay_seconds=Decimal("0"),
    )
    return MT5DemoBroker(config, risk_state, mt5_module=api, clock=lambda: NOW)


def make_plan() -> TradePlan:
    return TradePlan(
        decision_id="decision-shadow",
        event_id="event-1",
        strategy_id="event-reaction-retest-v1",
        symbol="US100",
        direction=Direction.LONG,
        created_at=NOW - timedelta(seconds=1),
        entry=Decimal("100.1"),
        stop=Decimal("99.0"),
        risk_amount=Decimal("50"),
        maximum_loss=Decimal("45"),
        quantity=Decimal("1.0"),
        configuration_hash="a" * 64,
        rationale=("shadow test",),
    )


class MT5ReadAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeReadMT5()
        self.read = MT5ReadAdapter(make_broker(self.api))

    def test_ticks_and_bid_ask_bars_are_normalized_from_ticks(self) -> None:
        start = NOW - timedelta(minutes=2)
        self.api.tick_rows = (
            SimpleNamespace(
                time_msc=int((NOW - timedelta(seconds=90)).timestamp() * 1000),
                bid=99.8,
                ask=100.0,
            ),
            SimpleNamespace(
                time_msc=int((NOW - timedelta(seconds=70)).timestamp() * 1000),
                bid=100.1,
                ask=100.3,
            ),
            SimpleNamespace(
                time_msc=int((NOW - timedelta(seconds=40)).timestamp() * 1000),
                bid=100.0,
                ask=100.2,
            ),
            SimpleNamespace(
                time_msc=int((NOW - timedelta(seconds=10)).timestamp() * 1000),
                bid=100.2,
                ask=100.4,
            ),
        )
        ticks = self.read.ticks_between("US100", start, NOW)
        self.assertEqual(len(ticks), 4)
        self.assertEqual(ticks[0].ask, Decimal("100.0"))
        bars = self.read.bars_between("US100", start, NOW, timeframe_seconds=60)
        self.assertGreaterEqual(len(bars), 1)
        self.assertTrue(all(bar.ask_high >= bar.bid_high for bar in bars))

    def test_latest_tick_staleness_and_future_are_fail_closed(self) -> None:
        tick = self.read.latest_tick("US100", at=NOW, maximum_age=timedelta(seconds=2))
        self.assertEqual(tick.bid, Decimal("100.0"))
        self.api.latest = SimpleNamespace(
            time_msc=int((NOW - timedelta(seconds=10)).timestamp() * 1000), bid=100, ask=101
        )
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.read.latest_tick("US100", at=NOW, maximum_age=timedelta(seconds=2))
        self.api.latest = SimpleNamespace(
            time_msc=int((NOW + timedelta(seconds=1)).timestamp() * 1000), bid=100, ask=101
        )
        with self.assertRaisesRegex(RuntimeError, "future"):
            self.read.latest_tick("US100", at=NOW, maximum_age=timedelta(seconds=2))

    def test_positions_orders_and_fills_preserve_broker_ids_and_mapping(self) -> None:
        self.api.position_rows = (
            SimpleNamespace(
                ticket=11,
                symbol="USTEC.cash",
                type=self.api.POSITION_TYPE_BUY,
                volume=0.5,
                price_open=100.1,
                sl=99.0,
            ),
        )
        self.api.order_rows = (
            SimpleNamespace(
                ticket=22,
                symbol="USTEC.cash",
                type=self.api.ORDER_TYPE_SELL_LIMIT,
                volume_current=0.3,
                volume_initial=0.3,
                price_open=101.0,
                sl=102.0,
                comment="CAT-test",
            ),
        )
        self.api.deal_rows = (
            SimpleNamespace(
                ticket=33,
                order=22,
                symbol="USTEC.cash",
                time_msc=int(NOW.timestamp() * 1000),
                volume=0.3,
                price=101.0,
                profit=-2.5,
            ),
            SimpleNamespace(
                ticket=34,
                order=999,
                symbol="USTEC.cash",
                time_msc=int(NOW.timestamp() * 1000),
                volume=0.1,
                price=100.0,
                profit=1.0,
            ),
        )
        positions = self.read.positions()
        orders = self.read.pending_orders()
        fills = self.read.fills_for_order(
            "22", start=NOW - timedelta(days=1), end=NOW + timedelta(seconds=1)
        )
        self.assertEqual(positions[0].logical_symbol, "US100")
        self.assertEqual(positions[0].direction, "long")
        self.assertEqual(orders[0].direction, "short")
        self.assertEqual(fills[0].broker_deal_id, "33")
        self.assertEqual(fills[0].profit, Decimal("-2.5"))
        self.assertEqual(len(fills), 1)

    def test_shadow_observation_never_sends_and_uses_executable_side(self) -> None:
        observation = self.read.shadow_observation(make_plan(), at=NOW)
        self.assertEqual(observation.broker_executable_price, Decimal("100.2"))
        self.assertEqual(observation.adverse_price_delta, Decimal("0.1"))
        self.assertFalse(self.read.broker.armed)

    def test_read_failures_and_invalid_ranges_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.read.ticks_between("US100", NOW, NOW)
        with self.assertRaises(ValueError):
            self.read.bars_between(
                "US100", NOW - timedelta(seconds=1), NOW, timeframe_seconds=0
            )
        with self.assertRaises(ValueError):
            self.read.latest_tick("US100", at=NOW, maximum_age=timedelta(0))
        self.api.tick_rows = None
        with self.assertRaises(RuntimeError):
            self.read.ticks_between("US100", NOW - timedelta(seconds=1), NOW)
        self.api.position_rows = None
        with self.assertRaises(RuntimeError):
            self.read.positions()
        self.api.position_rows = ()
        self.api.order_rows = None
        with self.assertRaises(RuntimeError):
            self.read.pending_orders()
        self.api.order_rows = ()
        self.api.deal_rows = None
        with self.assertRaises(RuntimeError):
            self.read.fills_for_order(
                "1", start=NOW - timedelta(seconds=1), end=NOW + timedelta(seconds=1)
            )

    def test_empty_fill_id_and_naive_time_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.read.fills_for_order(
                "", start=NOW - timedelta(seconds=1), end=NOW + timedelta(seconds=1)
            )
        with self.assertRaises(ValueError):
            self.read.ticks_between("US100", datetime(2030, 1, 1), NOW)


if __name__ == "__main__":
    unittest.main()
