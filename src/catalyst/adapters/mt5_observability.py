"""Read-only MT5 normalization for shadow mode and operator observability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from catalyst.adapters.mt5_broker import MT5DemoBroker
from catalyst.domain.enums import Direction
from catalyst.domain.models import TradePlan
from catalyst.replay.models import RawBar, RawTick


@dataclass(frozen=True, slots=True)
class MT5PositionView:
    broker_position_id: str
    broker_symbol: str
    logical_symbol: str | None
    direction: str
    volume: Decimal
    price_open: Decimal
    stop: Decimal | None


@dataclass(frozen=True, slots=True)
class MT5OrderView:
    broker_order_id: str
    broker_symbol: str
    logical_symbol: str | None
    direction: str
    volume: Decimal
    price_open: Decimal
    stop: Decimal | None
    comment: str


@dataclass(frozen=True, slots=True)
class MT5FillView:
    broker_deal_id: str
    broker_order_id: str
    broker_symbol: str
    logical_symbol: str | None
    occurred_at: datetime
    volume: Decimal
    price: Decimal
    profit: Decimal


@dataclass(frozen=True, slots=True)
class MT5ShadowObservation:
    decision_id: str
    symbol: str
    observed_at: datetime
    intended_entry: Decimal
    broker_executable_price: Decimal
    adverse_price_delta: Decimal
    bid: Decimal
    ask: Decimal


class MT5ReadAdapter:
    """Read-only companion around the verified MT5 demo broker connection."""

    def __init__(self, broker: MT5DemoBroker) -> None:
        self.broker = broker

    @staticmethod
    def _require_utc(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must be normalized to UTC")

    @staticmethod
    def _value(row: Any, name: str, default: object | None = None) -> object | None:
        if hasattr(row, name):
            return getattr(row, name)
        if isinstance(row, Mapping):
            return row.get(name, default)
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return default

    @staticmethod
    def _decimal(value: object | None, field_name: str, *, positive: bool = False) -> Decimal:
        if value is None:
            raise RuntimeError(f"MT5 field {field_name} is missing")
        result = Decimal(str(value))
        if not result.is_finite():
            raise RuntimeError(f"MT5 field {field_name} is non-finite")
        if positive and result <= 0:
            raise RuntimeError(f"MT5 field {field_name} must be positive")
        return result

    @classmethod
    def _timestamp(cls, row: Any) -> datetime:
        time_msc = cls._value(row, "time_msc")
        if time_msc is not None:
            return datetime.fromtimestamp(int(time_msc) / 1000, UTC)
        seconds = cls._value(row, "time")
        if seconds is None:
            raise RuntimeError("MT5 row has no timestamp")
        return datetime.fromtimestamp(int(seconds), UTC)

    def _ready(self) -> Any:
        self.broker._ensure_connected()
        self.broker._verify_demo_account()
        return self.broker._api()

    def _logical_symbol(self, broker_symbol: str) -> str | None:
        reverse = {value: key for key, value in self.broker.config.symbol_mapping.items()}
        return reverse.get(broker_symbol)

    def ticks_between(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[RawTick, ...]:
        self._require_utc(start, "start")
        self._require_utc(end, "end")
        if end <= start:
            raise ValueError("tick range end must follow start")
        api = self._ready()
        broker_symbol = self.broker._broker_symbol(symbol)
        rows = api.copy_ticks_range(broker_symbol, start, end, api.COPY_TICKS_ALL)
        if rows is None:
            raise RuntimeError("MT5 copy_ticks_range returned no data")
        ticks: list[RawTick] = []
        for sequence, row in enumerate(rows):
            bid = self._decimal(self._value(row, "bid"), "bid", positive=True)
            ask = self._decimal(self._value(row, "ask"), "ask", positive=True)
            timestamp = self._timestamp(row)
            if timestamp < start or timestamp > end:
                continue
            ticks.append(
                RawTick(
                    symbol=symbol,
                    timestamp=timestamp,
                    bid=bid,
                    ask=ask,
                    source_sequence=sequence,
                )
            )
        return tuple(ticks)

    def latest_tick(
        self,
        symbol: str,
        *,
        at: datetime,
        maximum_age: timedelta,
    ) -> RawTick:
        self._require_utc(at, "at")
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        api = self._ready()
        broker_symbol = self.broker._broker_symbol(symbol)
        row = api.symbol_info_tick(broker_symbol)
        if row is None:
            raise RuntimeError(f"MT5 latest tick unavailable: {broker_symbol}")
        tick = RawTick(
            symbol=symbol,
            timestamp=self._timestamp(row),
            bid=self._decimal(self._value(row, "bid"), "bid", positive=True),
            ask=self._decimal(self._value(row, "ask"), "ask", positive=True),
            source_sequence=0,
        )
        if tick.timestamp > at:
            raise RuntimeError("MT5 tick timestamp is in the future")
        if at - tick.timestamp > maximum_age:
            raise RuntimeError("MT5 tick is stale")
        return tick

    def bars_between(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        timeframe_seconds: int,
    ) -> tuple[RawBar, ...]:
        if timeframe_seconds <= 0:
            raise ValueError("timeframe_seconds must be positive")
        ticks = self.ticks_between(symbol, start, end)
        buckets: dict[int, list[RawTick]] = {}
        for tick in ticks:
            epoch = int(tick.timestamp.timestamp())
            bucket = epoch - (epoch % timeframe_seconds)
            buckets.setdefault(bucket, []).append(tick)
        bars: list[RawBar] = []
        for sequence, bucket in enumerate(sorted(buckets)):
            opened_at = datetime.fromtimestamp(bucket, UTC)
            closed_at = opened_at + timedelta(seconds=timeframe_seconds)
            if closed_at > end:
                continue
            group = sorted(buckets[bucket], key=lambda item: (item.timestamp, item.source_sequence))
            bids = tuple(item.bid for item in group)
            asks = tuple(item.ask for item in group)
            bars.append(
                RawBar(
                    symbol=symbol,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    bid_open=bids[0],
                    bid_high=max(bids),
                    bid_low=min(bids),
                    bid_close=bids[-1],
                    ask_open=asks[0],
                    ask_high=max(asks),
                    ask_low=min(asks),
                    ask_close=asks[-1],
                    source_sequence=sequence,
                )
            )
        return tuple(bars)

    def positions(self) -> tuple[MT5PositionView, ...]:
        api = self._ready()
        rows = api.positions_get()
        if rows is None:
            raise RuntimeError("MT5 positions could not be read")
        result: list[MT5PositionView] = []
        for row in rows:
            broker_symbol = str(self._value(row, "symbol", ""))
            position_type = self._value(row, "type")
            if position_type == getattr(api, "POSITION_TYPE_BUY", object()):
                direction = Direction.LONG.value
            elif position_type == getattr(api, "POSITION_TYPE_SELL", object()):
                direction = Direction.SHORT.value
            else:
                direction = "unknown"
            stop_raw = self._decimal(self._value(row, "sl", 0), "sl")
            result.append(
                MT5PositionView(
                    broker_position_id=str(self._value(row, "ticket", "")),
                    broker_symbol=broker_symbol,
                    logical_symbol=self._logical_symbol(broker_symbol),
                    direction=direction,
                    volume=self._decimal(self._value(row, "volume"), "volume", positive=True),
                    price_open=self._decimal(
                        self._value(row, "price_open"), "price_open", positive=True
                    ),
                    stop=stop_raw if stop_raw > 0 else None,
                )
            )
        return tuple(result)

    def pending_orders(self) -> tuple[MT5OrderView, ...]:
        api = self._ready()
        rows = api.orders_get()
        if rows is None:
            raise RuntimeError("MT5 pending orders could not be read")
        buy_types = {
            getattr(api, name, object())
            for name in ("ORDER_TYPE_BUY", "ORDER_TYPE_BUY_LIMIT", "ORDER_TYPE_BUY_STOP")
        }
        sell_types = {
            getattr(api, name, object())
            for name in ("ORDER_TYPE_SELL", "ORDER_TYPE_SELL_LIMIT", "ORDER_TYPE_SELL_STOP")
        }
        result: list[MT5OrderView] = []
        for row in rows:
            broker_symbol = str(self._value(row, "symbol", ""))
            order_type = self._value(row, "type")
            direction = (
                Direction.LONG.value
                if order_type in buy_types
                else Direction.SHORT.value
                if order_type in sell_types
                else "unknown"
            )
            stop_raw = self._decimal(self._value(row, "sl", 0), "sl")
            result.append(
                MT5OrderView(
                    broker_order_id=str(self._value(row, "ticket", "")),
                    broker_symbol=broker_symbol,
                    logical_symbol=self._logical_symbol(broker_symbol),
                    direction=direction,
                    volume=self._decimal(
                        self._value(row, "volume_current", self._value(row, "volume_initial")),
                        "volume",
                        positive=True,
                    ),
                    price_open=self._decimal(
                        self._value(row, "price_open"), "price_open", positive=True
                    ),
                    stop=stop_raw if stop_raw > 0 else None,
                    comment=str(self._value(row, "comment", "")),
                )
            )
        return tuple(result)

    def fills_for_order(
        self,
        broker_order_id: str,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[MT5FillView, ...]:
        if not broker_order_id.strip():
            raise ValueError("broker_order_id must not be empty")
        self._require_utc(start, "start")
        self._require_utc(end, "end")
        if end <= start:
            raise ValueError("fill range end must follow start")
        api = self._ready()
        rows = api.history_deals_get(start, end)
        if rows is None:
            raise RuntimeError("MT5 deal history could not be read")
        result: list[MT5FillView] = []
        for row in rows:
            if str(self._value(row, "order", "")) != broker_order_id:
                continue
            broker_symbol = str(self._value(row, "symbol", ""))
            result.append(
                MT5FillView(
                    broker_deal_id=str(self._value(row, "ticket", "")),
                    broker_order_id=broker_order_id,
                    broker_symbol=broker_symbol,
                    logical_symbol=self._logical_symbol(broker_symbol),
                    occurred_at=self._timestamp(row),
                    volume=self._decimal(self._value(row, "volume"), "volume", positive=True),
                    price=self._decimal(self._value(row, "price"), "price", positive=True),
                    profit=self._decimal(self._value(row, "profit", 0), "profit"),
                )
            )
        return tuple(result)

    def shadow_observation(
        self,
        plan: TradePlan,
        *,
        at: datetime,
        maximum_tick_age: timedelta = timedelta(seconds=2),
    ) -> MT5ShadowObservation:
        self.broker.contract_for(plan.symbol)
        tick = self.latest_tick(plan.symbol, at=at, maximum_age=maximum_tick_age)
        executable = tick.ask if plan.direction is Direction.LONG else tick.bid
        adverse = (
            executable - plan.entry
            if plan.direction is Direction.LONG
            else plan.entry - executable
        )
        return MT5ShadowObservation(
            decision_id=plan.decision_id,
            symbol=plan.symbol,
            observed_at=tick.timestamp,
            intended_entry=plan.entry,
            broker_executable_price=executable,
            adverse_price_delta=adverse,
            bid=tick.bid,
            ask=tick.ask,
        )
