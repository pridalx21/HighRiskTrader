"""Reduce-risk MT5 exit adapter for CATALYST-owned demo positions only.

Exits intentionally do not require the entry arm latch: a kill switch or disarm
must block new risk without preventing an already-open managed demo position
from being reduced. Every call still positively verifies the configured MT5
demo account, sends at most once, and fails closed on an ambiguous result.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Any

from catalyst.adapters.mt5_broker import MT5DemoBroker
from catalyst.domain.enums import Direction
from catalyst.ports.broker import OrderReceipt


@dataclass(frozen=True, slots=True)
class MT5ManagedPosition:
    broker_position_id: str
    logical_symbol: str
    direction: Direction
    volume: Decimal
    price_open: Decimal
    stop: Decimal | None
    comment: str

    def __post_init__(self) -> None:
        if not self.broker_position_id.strip() or not self.logical_symbol.strip():
            raise ValueError("managed position identifiers must not be empty")
        for field_name in ("volume", "price_open"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be a positive finite Decimal")
        if self.stop is not None and (
            not isinstance(self.stop, Decimal) or not self.stop.is_finite() or self.stop <= 0
        ):
            raise ValueError("stop must be a positive finite Decimal when present")
        if not self.comment.startswith("CAT-"):
            raise ValueError("managed position must carry a CATALYST comment")


class MT5ExitAdapter:
    """Discover and close only positions carrying this CATALYST magic/comment."""

    def __init__(self, broker: MT5DemoBroker) -> None:
        self.broker = broker

    @staticmethod
    def decision_comment(decision_id: str) -> str:
        if not decision_id.strip():
            raise ValueError("decision_id must not be empty")
        token = sha256(decision_id.encode("utf-8")).hexdigest()[:16]
        return f"CAT-{token}"

    def managed_positions(self) -> tuple[MT5ManagedPosition, ...]:
        self.broker._ensure_connected()
        self.broker._verify_demo_account()
        api = self.broker._api()
        rows = api.positions_get()
        if rows is None:
            raise RuntimeError("MT5 positions could not be read for exit management")
        reverse = {broker: logical for logical, broker in self.broker.config.symbol_mapping.items()}
        positions: list[MT5ManagedPosition] = []
        for row in rows:
            magic = int(getattr(row, "magic", -1))
            comment = str(getattr(row, "comment", ""))
            if magic != self.broker.config.magic or not comment.startswith("CAT-"):
                continue
            broker_symbol = str(getattr(row, "symbol", ""))
            logical_symbol = reverse.get(broker_symbol)
            if logical_symbol is None:
                raise RuntimeError("CATALYST position uses an unmapped broker symbol")
            position_type = getattr(row, "type", None)
            if position_type == getattr(api, "POSITION_TYPE_BUY", object()):
                direction = Direction.LONG
            elif position_type == getattr(api, "POSITION_TYPE_SELL", object()):
                direction = Direction.SHORT
            else:
                raise RuntimeError("CATALYST position has an unknown MT5 direction")
            stop_raw = self.broker._decimal(getattr(row, "sl", 0), "position.sl")
            positions.append(
                MT5ManagedPosition(
                    broker_position_id=str(getattr(row, "ticket", "")),
                    logical_symbol=logical_symbol,
                    direction=direction,
                    volume=self.broker._decimal(getattr(row, "volume", None), "position.volume"),
                    price_open=self.broker._decimal(
                        getattr(row, "price_open", None), "position.price_open"
                    ),
                    stop=stop_raw if stop_raw > 0 else None,
                    comment=comment,
                )
            )
        return tuple(positions)

    def close_position(self, position: MT5ManagedPosition, *, reason: str) -> OrderReceipt:
        """Send one opposite market deal referencing the exact managed position ticket."""

        if not reason.strip():
            raise ValueError("exit reason must not be empty")
        self.broker._ensure_connected()
        self.broker._verify_demo_account()
        contract = self.broker.contract_for(position.logical_symbol)
        if position.volume < contract.volume_minimum or position.volume > contract.volume_maximum:
            raise RuntimeError("managed exit volume is outside broker limits")
        if position.volume % contract.volume_step != Decimal("0"):
            raise RuntimeError("managed exit volume is not aligned to broker volume step")

        api = self.broker._api()
        broker_symbol = self.broker._broker_symbol(position.logical_symbol)
        if not bool(api.symbol_select(broker_symbol, True)):
            raise RuntimeError(f"MT5 symbol could not be selected for exit: {broker_symbol}")
        tick = api.symbol_info_tick(broker_symbol)
        if tick is None:
            raise RuntimeError("MT5 executable exit quote is unavailable")
        if position.direction is Direction.LONG:
            order_type = api.ORDER_TYPE_SELL
            price = self.broker._decimal(getattr(tick, "bid", None), "exit.bid")
        else:
            order_type = api.ORDER_TYPE_BUY
            price = self.broker._decimal(getattr(tick, "ask", None), "exit.ask")
        if price <= 0:
            raise RuntimeError("MT5 executable exit price must be positive")

        client_id = f"exit:{position.broker_position_id}"
        request = {
            "action": api.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "position": int(position.broker_position_id),
            "volume": float(position.volume),
            "type": order_type,
            "price": float(price),
            "deviation": self.broker.config.deviation_points,
            "magic": self.broker.config.magic,
            "comment": self._exit_comment(position.broker_position_id, reason),
            "type_time": api.ORDER_TIME_GTC,
            "type_filling": api.ORDER_FILLING_RETURN,
        }
        checked = api.order_check(request)
        if checked is None:
            raise RuntimeError("MT5 exit order_check returned no result")
        check_code = int(getattr(checked, "retcode", -1))
        check_ok = check_code in {
            0,
            int(getattr(api, "TRADE_RETCODE_DONE", -999999)),
            int(getattr(api, "TRADE_RETCODE_PLACED", -999998)),
        }
        if not check_ok:
            return OrderReceipt(
                accepted=False,
                client_order_id=client_id,
                broker_order_id=None,
                code=f"MT5_EXIT_CHECK_{check_code}",
                message=str(getattr(checked, "comment", "exit order_check rejected")),
            )

        result = api.order_send(request)
        if result is None:
            raise TimeoutError("MT5 exit order_send returned no result; outcome is uncertain")
        retcode = int(getattr(result, "retcode", -1))
        accepted_codes = {
            int(getattr(api, "TRADE_RETCODE_DONE", -999999)),
            int(getattr(api, "TRADE_RETCODE_DONE_PARTIAL", -999998)),
            int(getattr(api, "TRADE_RETCODE_PLACED", -999997)),
        }
        accepted = retcode in accepted_codes
        broker_id_raw: Any = getattr(result, "order", None) or getattr(result, "deal", None)
        broker_order_id = str(broker_id_raw) if accepted and broker_id_raw else None
        if accepted and broker_order_id is None:
            raise TimeoutError("MT5 accepted exit without a stable broker/deal id")
        return OrderReceipt(
            accepted=accepted,
            client_order_id=client_id,
            broker_order_id=broker_order_id,
            code=f"MT5_EXIT_{retcode}",
            message=str(getattr(result, "comment", "MT5 exit result")),
        )

    @staticmethod
    def _exit_comment(position_id: str, reason: str) -> str:
        token = sha256(f"{position_id}:{reason}".encode("utf-8")).hexdigest()[:12]
        return f"CAT-X-{token}"
