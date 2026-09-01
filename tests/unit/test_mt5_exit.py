from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from catalyst.adapters.mt5_broker import (
    MT5AccountRiskState,
    MT5DemoBroker,
    MT5DemoConfig,
    MT5SymbolEconomics,
)
from catalyst.adapters.mt5_exit import MT5ExitAdapter
from catalyst.domain.enums import Direction

NOW = datetime(2030, 1, 10, 14, 0, tzinfo=UTC)


class FakeExitMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008

    def __init__(self) -> None:
        self.check_retcode = 0
        self.send_result: object | None = SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=9001,
            deal=8001,
            comment="closed",
        )
        self.sent_requests: list[dict[str, object]] = []
        self.position_rows: list[object] = []

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

    def positions_get(self) -> tuple[object, ...]:
        return tuple(self.position_rows)

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        return symbol == "USTEC.cash" and selected

    def symbol_info_tick(self, symbol: str) -> object | None:
        if symbol != "USTEC.cash":
            return None
        return SimpleNamespace(bid=101.0, ask=101.2)

    def order_check(self, request: dict[str, object]) -> object:
        return SimpleNamespace(retcode=self.check_retcode, comment="check")

    def order_send(self, request: dict[str, object]) -> object | None:
        self.sent_requests.append(request)
        result = self.send_result
        if result is not None and int(getattr(result, "retcode", -1)) == self.TRADE_RETCODE_DONE:
            ticket = int(request["position"])
            self.position_rows = [
                row for row in self.position_rows if int(getattr(row, "ticket", -1)) != ticket
            ]
        return result


def risk_state() -> MT5AccountRiskState:
    return MT5AccountRiskState(
        day_start_equity=Decimal("1000"),
        month_start_equity=Decimal("1000"),
        daily_realized_pnl=Decimal("0"),
        consecutive_losses=0,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0"),
    )


def broker(api: FakeExitMT5) -> MT5DemoBroker:
    return MT5DemoBroker(
        MT5DemoConfig(
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
        ),
        risk_state,
        mt5_module=api,
        clock=lambda: NOW,
    )


def catalyst_position(api: FakeExitMT5, *, stop: float = 99.0) -> object:
    return SimpleNamespace(
        ticket=77,
        symbol="USTEC.cash",
        type=api.POSITION_TYPE_BUY,
        volume=0.5,
        price_open=100.5,
        sl=stop,
        magic=26083101,
        comment=MT5ExitAdapter.decision_comment("decision-1"),
    )


class MT5ExitAdapterTests(unittest.TestCase):
    def test_only_catalyst_magic_and_comment_are_managed(self) -> None:
        api = FakeExitMT5()
        api.position_rows = [
            catalyst_position(api),
            SimpleNamespace(
                ticket=88,
                symbol="USTEC.cash",
                type=api.POSITION_TYPE_BUY,
                volume=0.2,
                price_open=100.0,
                sl=99.0,
                magic=1,
                comment="manual",
            ),
        ]
        exit_adapter = MT5ExitAdapter(broker(api))
        positions = exit_adapter.managed_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].broker_position_id, "77")
        self.assertEqual(positions[0].direction, Direction.LONG)
        self.assertEqual(positions[0].logical_symbol, "US100")

    def test_close_is_reduce_risk_and_does_not_require_entry_arm(self) -> None:
        api = FakeExitMT5()
        api.position_rows = [catalyst_position(api)]
        mt5 = broker(api)
        exit_adapter = MT5ExitAdapter(mt5)
        position = exit_adapter.managed_positions()[0]
        self.assertFalse(mt5.armed)
        receipt = exit_adapter.close_position(position, reason="session_cutoff")
        self.assertTrue(receipt.accepted)
        self.assertEqual(len(api.sent_requests), 1)
        request = api.sent_requests[0]
        self.assertEqual(request["position"], 77)
        self.assertEqual(request["type"], api.ORDER_TYPE_SELL)
        self.assertEqual(request["price"], 101.0)
        self.assertEqual(exit_adapter.managed_positions(), ())

    def test_missing_stop_is_exposed_for_runtime_emergency_exit(self) -> None:
        api = FakeExitMT5()
        api.position_rows = [catalyst_position(api, stop=0.0)]
        position = MT5ExitAdapter(broker(api)).managed_positions()[0]
        self.assertIsNone(position.stop)

    def test_exit_check_rejection_never_sends(self) -> None:
        api = FakeExitMT5()
        api.position_rows = [catalyst_position(api)]
        api.check_retcode = 10013
        exit_adapter = MT5ExitAdapter(broker(api))
        receipt = exit_adapter.close_position(
            exit_adapter.managed_positions()[0],
            reason="range_reclaim",
        )
        self.assertFalse(receipt.accepted)
        self.assertEqual(api.sent_requests, [])

    def test_ambiguous_exit_sends_once_and_raises_timeout(self) -> None:
        api = FakeExitMT5()
        api.position_rows = [catalyst_position(api)]
        api.send_result = None
        exit_adapter = MT5ExitAdapter(broker(api))
        with self.assertRaises(TimeoutError):
            exit_adapter.close_position(
                exit_adapter.managed_positions()[0],
                reason="session_cutoff",
            )
        self.assertEqual(len(api.sent_requests), 1)


if __name__ == "__main__":
    unittest.main()
