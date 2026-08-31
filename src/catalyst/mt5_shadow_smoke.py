"""Opt-in Windows MT5 shadow smoke test with zero order submission."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from json import loads
from pathlib import Path
from typing import Any

from catalyst.adapters.mt5_broker import (
    MT5AccountRiskState,
    MT5DemoBroker,
    MT5DemoConfig,
    MT5SymbolEconomics,
)
from catalyst.adapters.mt5_observability import MT5ReadAdapter


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _mapping(raw: str) -> dict[str, str]:
    value: Any = loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("CATALYST_MT5_SYMBOL_MAPPING_JSON must be a non-empty object")
    result: dict[str, str] = {}
    for key, item in value.items():
        logical = str(key).strip()
        broker = str(item).strip()
        if not logical or not broker:
            raise ValueError("symbol mappings must contain non-empty names")
        result[logical] = broker
    return result


def _economics(raw: str) -> dict[str, MT5SymbolEconomics]:
    value: Any = loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("CATALYST_MT5_ECONOMICS_JSON must be a non-empty object")
    result: dict[str, MT5SymbolEconomics] = {}
    for symbol, item in value.items():
        if not isinstance(item, dict):
            raise ValueError("each MT5 economics entry must be an object")
        result[str(symbol)] = MT5SymbolEconomics(
            commission_per_volume=Decimal(str(item["commission_per_volume"])),
            slippage_ticks=Decimal(str(item["slippage_ticks"])),
            profit_to_account_rate=Decimal(str(item["profit_to_account_rate"])),
        )
    return result


def _risk_state() -> MT5AccountRiskState:
    return MT5AccountRiskState(
        day_start_equity=Decimal("1"),
        month_start_equity=Decimal("1"),
        daily_realized_pnl=Decimal("0"),
        consecutive_losses=0,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0"),
    )


def main() -> None:
    symbol_mapping = _mapping(_required("CATALYST_MT5_SYMBOL_MAPPING_JSON"))
    economics = _economics(_required("CATALYST_MT5_ECONOMICS_JSON"))
    config = MT5DemoConfig(
        terminal_path=Path(_required("CATALYST_MT5_TERMINAL_PATH")),
        login=int(_required("CATALYST_MT5_LOGIN")),
        server=_required("CATALYST_MT5_SERVER"),
        symbol_mapping=symbol_mapping,
        symbol_economics=economics,
        auto_execution_enabled=False,
    )
    broker = MT5DemoBroker(config, _risk_state)
    read = MT5ReadAdapter(broker)
    try:
        broker.connect()
        now = datetime.now(UTC)
        for symbol in sorted(symbol_mapping):
            contract = broker.contract_for(symbol)
            tick = read.latest_tick(symbol, at=now, maximum_age=timedelta(seconds=5))
            print(
                f"symbol={symbol} tick={tick.bid}/{tick.ask} "
                f"tick_size={contract.tick_size} volume_step={contract.volume_step}"
            )
        print(f"positions={len(read.positions())}")
        print(f"pending_orders={len(read.pending_orders())}")
        print("mt5_shadow_smoke=pass orders_sent=0")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
