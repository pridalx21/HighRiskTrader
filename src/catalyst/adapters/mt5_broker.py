"""Fail-closed MetaTrader 5 demo adapter.

The adapter keeps MT5 and environment-specific behavior outside the deterministic
core. Unit tests inject a fake MT5 module; importing this module never imports or
connects to MetaTrader5 by itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from time import sleep
from types import ModuleType
from typing import Any

from catalyst.domain.enums import AccountMode, Direction
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.journal import OrderIntentRecord
from catalyst.ports.reconciliation import BrokerOrderLookup, BrokerOrderState


@dataclass(frozen=True, slots=True)
class MT5SymbolEconomics:
    """Explicit non-discoverable economics required for safe sizing."""

    commission_per_volume: Decimal
    slippage_ticks: Decimal
    profit_to_account_rate: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "commission_per_volume",
            "slippage_ticks",
            "profit_to_account_rate",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{field_name} must be a finite Decimal")
        if self.commission_per_volume < 0 or self.slippage_ticks < 0:
            raise ValueError("commission and slippage allowances must be non-negative")
        if self.profit_to_account_rate <= 0:
            raise ValueError("profit_to_account_rate must be positive")
        if self.commission_per_volume == 0 and self.slippage_ticks == 0:
            raise ValueError("a pessimistic commission or slippage allowance is required")


@dataclass(frozen=True, slots=True)
class MT5AccountRiskState:
    """Risk state owned by the journal/risk layer, not inferred from MT5."""

    day_start_equity: Decimal
    month_start_equity: Decimal
    daily_realized_pnl: Decimal
    consecutive_losses: int
    active_risk_clusters: int
    open_worst_case_risk: Decimal

    def __post_init__(self) -> None:
        for field_name in ("day_start_equity", "month_start_equity"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be a positive finite Decimal")
        for field_name in ("daily_realized_pnl", "open_worst_case_risk"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{field_name} must be a finite Decimal")
        if self.open_worst_case_risk < 0:
            raise ValueError("open_worst_case_risk must be non-negative")
        if self.consecutive_losses < 0 or self.active_risk_clusters < 0:
            raise ValueError("loss and cluster counts must be non-negative")


@dataclass(frozen=True, slots=True)
class MT5DemoConfig:
    terminal_path: Path
    login: int
    server: str
    symbol_mapping: Mapping[str, str]
    symbol_economics: Mapping[str, MT5SymbolEconomics]
    auto_execution_enabled: bool = False
    reconnect_attempts: int = 2
    reconnect_delay_seconds: Decimal = Decimal("0.5")
    deviation_points: int = 10
    magic: int = 26083101

    def __post_init__(self) -> None:
        if not str(self.terminal_path).strip():
            raise ValueError("terminal_path must not be empty")
        if self.login <= 0:
            raise ValueError("login must be positive")
        if not self.server.strip():
            raise ValueError("server must not be empty")
        if not self.symbol_mapping:
            raise ValueError("symbol_mapping must not be empty")
        if set(self.symbol_mapping) != set(self.symbol_economics):
            raise ValueError("every logical symbol requires explicit economics")
        if any(
            not logical.strip() or not broker.strip()
            for logical, broker in self.symbol_mapping.items()
        ):
            raise ValueError("symbol mappings must contain non-empty names")
        if self.reconnect_attempts < 0:
            raise ValueError("reconnect_attempts must be non-negative")
        if self.reconnect_delay_seconds < 0:
            raise ValueError("reconnect_delay_seconds must be non-negative")
        if self.deviation_points < 0 or self.magic <= 0:
            raise ValueError("deviation_points and magic must be non-negative/positive")


class MT5DemoBroker:
    """BrokerPort + reconciliation adapter for one verified demo account."""

    def __init__(
        self,
        config: MT5DemoConfig,
        risk_state_provider: Callable[[], MT5AccountRiskState],
        *,
        mt5_module: ModuleType | Any | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.config = config
        self._risk_state_provider = risk_state_provider
        self._mt5 = mt5_module
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self._connected = False
        self._armed = False

    @property
    def armed(self) -> bool:
        return self._armed

    def _api(self) -> Any:
        if self._mt5 is None:
            self._mt5 = import_module("MetaTrader5")
        return self._mt5

    def connect(self) -> None:
        """Connect with bounded retries and positively verify demo mode."""

        api = self._api()
        attempts = self.config.reconnect_attempts + 1
        last_error: object = None
        for attempt in range(attempts):
            initialized = bool(api.initialize(path=str(self.config.terminal_path)))
            logged_in = initialized and bool(
                api.login(self.config.login, server=self.config.server)
            )
            if logged_in:
                self._connected = True
                try:
                    self._verify_demo_account()
                except Exception:
                    self._connected = False
                    self._armed = False
                    raise
                return
            last_error = api.last_error()
            self._connected = False
            self._armed = False
            if attempt + 1 < attempts:
                self._sleeper(float(self.config.reconnect_delay_seconds))
        raise RuntimeError(f"MT5 connection failed after bounded retries: {last_error!r}")

    def disconnect(self) -> None:
        self._armed = False
        if self._mt5 is not None:
            self._mt5.shutdown()
        self._connected = False

    def arm_demo_execution(self) -> None:
        """Explicit per-process arming; never survives restart or disconnect."""

        if not self.config.auto_execution_enabled:
            raise RuntimeError("automatic demo execution is disabled by configuration")
        self._ensure_connected()
        self._verify_demo_account()
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    def _ensure_connected(self) -> None:
        if not self._connected:
            self.connect()
            return
        terminal = self._api().terminal_info()
        if terminal is None or not bool(getattr(terminal, "connected", False)):
            self._connected = False
            self._armed = False
            self.connect()

    def _verify_demo_account(self) -> Any:
        api = self._api()
        account = api.account_info()
        if account is None:
            self._armed = False
            raise RuntimeError("MT5 account mode cannot be verified")
        if int(getattr(account, "login", -1)) != self.config.login:
            self._armed = False
            raise RuntimeError("MT5 account login does not match configured demo login")
        if str(getattr(account, "server", "")) != self.config.server:
            self._armed = False
            raise RuntimeError("MT5 account server does not match configured demo server")
        demo_mode = getattr(api, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_mode is None or getattr(account, "trade_mode", None) != demo_mode:
            self._armed = False
            raise RuntimeError("MT5 account is not positively identified as demo")
        return account

    @staticmethod
    def _decimal(value: object, field_name: str) -> Decimal:
        if value is None:
            raise RuntimeError(f"MT5 field {field_name} is missing")
        result = Decimal(str(value))
        if not result.is_finite():
            raise RuntimeError(f"MT5 field {field_name} is non-finite")
        return result

    def account_snapshot(self) -> AccountSnapshot:
        self._ensure_connected()
        account = self._verify_demo_account()
        terminal = self._api().terminal_info()
        connected = terminal is not None and bool(getattr(terminal, "connected", False))
        if not connected:
            self._armed = False
        risk = self._risk_state_provider()
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise RuntimeError("MT5 adapter clock must return timezone-aware UTC")
        return AccountSnapshot(
            mode=AccountMode.DEMO,
            currency=str(getattr(account, "currency", "")),
            balance=self._decimal(getattr(account, "balance", None), "balance"),
            equity=self._decimal(getattr(account, "equity", None), "equity"),
            day_start_equity=risk.day_start_equity,
            month_start_equity=risk.month_start_equity,
            daily_realized_pnl=risk.daily_realized_pnl,
            consecutive_losses=risk.consecutive_losses,
            active_risk_clusters=risk.active_risk_clusters,
            open_worst_case_risk=risk.open_worst_case_risk,
            timestamp=timestamp.astimezone(UTC),
            connected=connected,
        )

    def _broker_symbol(self, logical_symbol: str) -> str:
        try:
            return self.config.symbol_mapping[logical_symbol]
        except KeyError as exc:
            raise RuntimeError(f"logical symbol is not mapped: {logical_symbol}") from exc

    def contract_for(self, symbol: str) -> BrokerContract:
        self._ensure_connected()
        account = self._verify_demo_account()
        broker_symbol = self._broker_symbol(symbol)
        info = self._api().symbol_info(broker_symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol metadata unavailable: {broker_symbol}")
        economics = self.config.symbol_economics[symbol]
        profit_currency = str(getattr(info, "currency_profit", ""))
        account_currency = str(getattr(account, "currency", ""))
        if profit_currency == account_currency and economics.profit_to_account_rate != Decimal("1"):
            raise RuntimeError("same-currency MT5 conversion rate must equal 1")
        return BrokerContract(
            symbol=symbol,
            tick_size=self._decimal(getattr(info, "trade_tick_size", None), "trade_tick_size"),
            tick_value=self._decimal(
                getattr(info, "trade_tick_value", None), "trade_tick_value"
            ),
            contract_size=self._decimal(
                getattr(info, "trade_contract_size", None), "trade_contract_size"
            ),
            profit_currency=profit_currency,
            account_currency=account_currency,
            profit_to_account_rate=economics.profit_to_account_rate,
            volume_minimum=self._decimal(getattr(info, "volume_min", None), "volume_min"),
            volume_maximum=self._decimal(getattr(info, "volume_max", None), "volume_max"),
            volume_step=self._decimal(getattr(info, "volume_step", None), "volume_step"),
            commission_per_volume=economics.commission_per_volume,
            slippage_ticks=economics.slippage_ticks,
        )

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        """Submit exactly one market order with its initial server-side stop."""

        if not self._armed:
            raise RuntimeError("automatic demo execution is not explicitly armed")
        self._ensure_connected()
        self._verify_demo_account()
        if not plan.server_side_stop_required:
            raise RuntimeError("broker-side protective stop is mandatory")
        contract = self.contract_for(plan.symbol)
        if plan.quantity < contract.volume_minimum or plan.quantity > contract.volume_maximum:
            raise RuntimeError("planned volume is outside broker limits")
        if plan.quantity % contract.volume_step != Decimal("0"):
            raise RuntimeError("planned volume is not aligned to broker volume step")

        api = self._api()
        broker_symbol = self._broker_symbol(plan.symbol)
        if not bool(api.symbol_select(broker_symbol, True)):
            raise RuntimeError(f"MT5 symbol could not be selected: {broker_symbol}")
        order_type = api.ORDER_TYPE_BUY if plan.direction is Direction.LONG else api.ORDER_TYPE_SELL
        request = {
            "action": api.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": float(plan.quantity),
            "type": order_type,
            "price": float(plan.entry),
            "sl": float(plan.stop),
            "deviation": self.config.deviation_points,
            "magic": self.config.magic,
            "comment": self._comment(plan.decision_id),
            "type_time": api.ORDER_TIME_GTC,
            "type_filling": api.ORDER_FILLING_RETURN,
        }
        checked = api.order_check(request)
        if checked is None:
            raise RuntimeError("MT5 order_check returned no result")
        check_code = int(getattr(checked, "retcode", -1))
        check_ok = check_code in {
            0,
            int(getattr(api, "TRADE_RETCODE_DONE", -999999)),
            int(getattr(api, "TRADE_RETCODE_PLACED", -999998)),
        }
        if not check_ok:
            return OrderReceipt(
                accepted=False,
                client_order_id=plan.decision_id,
                broker_order_id=None,
                code=f"MT5_CHECK_{check_code}",
                message=str(getattr(checked, "comment", "order_check rejected")),
            )

        result = api.order_send(request)
        if result is None:
            raise TimeoutError("MT5 order_send returned no result; outcome is uncertain")
        retcode = int(getattr(result, "retcode", -1))
        accepted_codes = {
            int(getattr(api, "TRADE_RETCODE_DONE", -999999)),
            int(getattr(api, "TRADE_RETCODE_DONE_PARTIAL", -999998)),
            int(getattr(api, "TRADE_RETCODE_PLACED", -999997)),
        }
        accepted = retcode in accepted_codes
        broker_id_raw = getattr(result, "order", None)
        broker_order_id = str(broker_id_raw) if accepted and broker_id_raw else None
        if accepted and broker_order_id is None:
            raise TimeoutError("MT5 accepted order without stable broker order id")
        return OrderReceipt(
            accepted=accepted,
            client_order_id=plan.decision_id,
            broker_order_id=broker_order_id,
            code=f"MT5_{retcode}",
            message=str(getattr(result, "comment", "MT5 order result")),
        )

    @staticmethod
    def _comment(decision_id: str) -> str:
        token = sha256(decision_id.encode("utf-8")).hexdigest()[:16]
        return f"CAT-{token}"

    def lookup_order(self, intent: OrderIntentRecord) -> BrokerOrderLookup:
        """Read-only restart lookup; this method never arms or submits."""

        self._ensure_connected()
        self._verify_demo_account()
        token = self._comment(intent.decision_id)
        logical_symbol = self._symbol_from_plan_json(intent.plan_json)
        broker_symbol = self._broker_symbol(logical_symbol)

        open_orders = self._api().orders_get(symbol=broker_symbol)
        match = self._matching_order(open_orders, token)
        if match is not None:
            return BrokerOrderLookup(
                BrokerOrderState.FOUND_OPEN,
                str(getattr(match, "ticket")),
                "matching MT5 open order found by deterministic client comment",
            )

        end = self._clock()
        if end.tzinfo is None or end.utcoffset() != timedelta(0):
            raise RuntimeError("MT5 adapter clock must return timezone-aware UTC")
        start = intent.created_at - timedelta(days=1)
        history = self._api().history_orders_get(start, end)
        match = self._matching_order(history, token)
        if match is not None:
            return BrokerOrderLookup(
                BrokerOrderState.FOUND_FILLED,
                str(getattr(match, "ticket")),
                "matching MT5 historical order found by deterministic client comment",
            )
        if open_orders is None or history is None:
            return BrokerOrderLookup(
                BrokerOrderState.UNKNOWN,
                None,
                "MT5 order history could not be read completely",
            )
        return BrokerOrderLookup(
            BrokerOrderState.NOT_FOUND,
            None,
            "no matching MT5 order found; intent remains unresolved and disarmed",
        )

    @staticmethod
    def _matching_order(orders: Sequence[Any] | None, token: str) -> Any | None:
        if orders is None:
            return None
        for order in orders:
            if str(getattr(order, "comment", "")) == token:
                return order
        return None

    @staticmethod
    def _symbol_from_plan_json(plan_json: str) -> str:
        from json import loads

        try:
            payload = loads(plan_json)
            symbol = payload["symbol"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("durable plan JSON does not contain a valid symbol") from exc
        if not isinstance(symbol, str) or not symbol.strip():
            raise RuntimeError("durable plan JSON symbol is invalid")
        return symbol
