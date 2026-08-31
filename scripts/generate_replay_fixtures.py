"""Regenerate the checked-in deterministic Phase 2 replay fixtures."""

from __future__ import annotations

from copy import deepcopy
from json import dumps
from pathlib import Path


def tick(symbol: str, timestamp: str, bid: str, ask: str, sequence: int) -> dict:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "bid": bid,
        "ask": ask,
        "source_sequence": sequence,
    }


def base_scenario() -> dict:
    return {
        "scenario_id": "long_pass",
        "event": {
            "event_id": "SYNTH_EVENT_001",
            "name": "Synthetic high-impact release",
            "scheduled_at": "2030-01-10T13:30:00Z",
            "ingested_at": "2030-01-09T13:30:00Z",
            "currency": "USD",
            "importance": "high",
            "status": "scheduled",
            "eligible_symbols": ["PRIMARY"],
            "source": "synthetic_fixture",
        },
        "primary_symbol": "PRIMARY",
        "ticks": [
            tick("PRIMARY", "2030-01-10T13:00:00Z", "99.8", "100.0", 1),
            tick("PRIMARY", "2030-01-10T13:10:00Z", "95.0", "95.2", 2),
            tick("PRIMARY", "2030-01-10T13:20:00Z", "97.9", "98.1", 3),
            tick("R1", "2030-01-10T13:20:00Z", "49.9", "50.1", 1),
            tick("R2", "2030-01-10T13:20:00Z", "69.9", "70.1", 1),
            tick("PRIMARY", "2030-01-10T13:31:30Z", "100.2", "100.4", 4),
            tick("PRIMARY", "2030-01-10T13:32:00Z", "100.0", "100.2", 5),
            tick("R1", "2030-01-10T13:32:09Z", "50.9", "51.1", 2),
            tick("R2", "2030-01-10T13:32:09Z", "70.9", "71.1", 2),
            tick("PRIMARY", "2030-01-10T13:32:10Z", "101.2", "101.4", 6),
            tick("PRIMARY", "2030-01-10T13:32:10.100000Z", "101.3", "101.5", 7),
            tick("PRIMARY", "2030-01-10T13:35:00Z", "102.8", "103.0", 8),
            tick("PRIMARY", "2030-01-10T13:40:00Z", "102.0", "102.2", 9),
        ],
        "bars": [
            {
                "symbol": "PRIMARY",
                "opened_at": "2030-01-10T13:00:00Z",
                "closed_at": "2030-01-10T13:30:00Z",
                "bid_open": "99.0",
                "bid_high": "99.8",
                "bid_low": "95.0",
                "bid_close": "97.9",
                "ask_open": "99.2",
                "ask_high": "100.0",
                "ask_low": "95.2",
                "ask_close": "98.1",
                "source_sequence": 1,
            }
        ],
        "related_rules": [
            {"symbol": "R1", "polarity": 1, "minimum_move": "0.5"},
            {"symbol": "R2", "polarity": 1, "minimum_move": "0.5"},
        ],
        "account": {
            "mode": "demo",
            "currency": "CHF",
            "balance": "1000.00",
            "equity": "1000.00",
            "day_start_equity": "1000.00",
            "month_start_equity": "1000.00",
            "daily_realized_pnl": "0.00",
            "consecutive_losses": 0,
            "active_risk_clusters": 0,
            "open_worst_case_risk": "0.00",
            "timestamp": "2030-01-10T13:32:10Z",
            "connected": True,
        },
        "contract": {
            "symbol": "PRIMARY",
            "tick_size": "0.1",
            "tick_value": "1",
            "contract_size": "1",
            "profit_currency": "CHF",
            "account_currency": "CHF",
            "profit_to_account_rate": "1",
            "volume_minimum": "0.1",
            "volume_maximum": "100",
            "volume_step": "0.1",
            "commission_per_volume": "0.01",
            "slippage_ticks": "1",
        },
        "execution": {
            "latency_milliseconds": 100,
            "maximum_adverse_slippage_ticks": "1",
            "fill_fraction": "1",
            "rejection_code": None,
        },
        "evaluation_delay_seconds": "0",
        "session_cutoff": "2030-01-10T13:40:00Z",
        "market_open": True,
        "emergency_exit": False,
    }


def expected(
    code: str,
    direction: str | None,
    execution_status: str | None = None,
    exit_reason: str | None = None,
) -> dict:
    return {
        "decision_code": code,
        "direction": direction,
        "execution_status": execution_status,
        "exit_reason": exit_reason,
    }


def fixtures() -> dict[str, dict]:
    long_pass = base_scenario()
    cases = {
        "long_pass": {
            "scenario": long_pass,
            "expected": expected("TRADE_PLAN_READY", "long", "filled", "session_cutoff"),
        }
    }

    short_pass = deepcopy(long_pass)
    short_pass["scenario_id"] = "short_pass"
    short_pass["ticks"] = [
        *short_pass["ticks"][:5],
        tick("PRIMARY", "2030-01-10T13:31:30Z", "94.6", "94.8", 4),
        tick("PRIMARY", "2030-01-10T13:32:00Z", "94.8", "95.0", 5),
        tick("R1", "2030-01-10T13:32:09Z", "48.9", "49.1", 2),
        tick("R2", "2030-01-10T13:32:09Z", "68.9", "69.1", 2),
        tick("PRIMARY", "2030-01-10T13:32:10Z", "92.8", "93.0", 6),
        tick("PRIMARY", "2030-01-10T13:32:10.100000Z", "92.7", "92.9", 7),
        tick("PRIMARY", "2030-01-10T13:35:00Z", "91.8", "92.0", 8),
        tick("PRIMARY", "2030-01-10T13:40:00Z", "92.0", "92.2", 9),
    ]
    cases["short_pass"] = {
        "scenario": short_pass,
        "expected": expected("TRADE_PLAN_READY", "short", "filled", "session_cutoff"),
    }

    whipsaw = deepcopy(long_pass)
    whipsaw["scenario_id"] = "whipsaw"
    whipsaw["account"]["timestamp"] = "2030-01-10T13:31:40Z"
    whipsaw["ticks"] = [
        *whipsaw["ticks"][:5],
        tick("PRIMARY", "2030-01-10T13:31:30Z", "100.2", "100.4", 4),
        tick("R1", "2030-01-10T13:31:39Z", "50.9", "51.1", 2),
        tick("R2", "2030-01-10T13:31:39Z", "70.9", "71.1", 2),
        tick("PRIMARY", "2030-01-10T13:31:40Z", "94.7", "94.9", 5),
    ]
    cases["whipsaw"] = {
        "scenario": whipsaw,
        "expected": expected("RETEST_INVALID", "short"),
    }

    stale = deepcopy(long_pass)
    stale["scenario_id"] = "stale_data"
    stale["evaluation_delay_seconds"] = "3"
    stale["account"]["timestamp"] = "2030-01-10T13:32:13Z"
    cases["stale_data"] = {
        "scenario": stale,
        "expected": expected("DATA_STALE", "long"),
    }

    spread = deepcopy(long_pass)
    spread["scenario_id"] = "spread_spike"
    for item in spread["ticks"]:
        if item["timestamp"] == "2030-01-10T13:32:10Z" and item["symbol"] == "PRIMARY":
            item["bid"] = "101.0"
            item["ask"] = "101.6"
    cases["spread_spike"] = {
        "scenario": spread,
        "expected": expected("SPREAD_TOO_WIDE", "long"),
    }

    missing = deepcopy(long_pass)
    missing["scenario_id"] = "missing_confirmation"
    missing["related_rules"] = missing["related_rules"][:1]
    missing["ticks"] = [item for item in missing["ticks"] if item["symbol"] != "R2"]
    cases["missing_confirmation"] = {
        "scenario": missing,
        "expected": expected("RELATED_MARKETS_MISSING", "long"),
    }

    late = deepcopy(long_pass)
    late["scenario_id"] = "late_setup"
    late["session_cutoff"] = "2030-01-10T14:00:00Z"
    late["account"]["timestamp"] = "2030-01-10T13:46:20Z"
    late["ticks"] = [
        *late["ticks"][:5],
        tick("PRIMARY", "2030-01-10T13:46:00Z", "100.2", "100.4", 4),
        tick("PRIMARY", "2030-01-10T13:46:10Z", "100.0", "100.2", 5),
        tick("R1", "2030-01-10T13:46:19Z", "50.9", "51.1", 2),
        tick("R2", "2030-01-10T13:46:19Z", "70.9", "71.1", 2),
        tick("PRIMARY", "2030-01-10T13:46:20Z", "101.2", "101.4", 6),
    ]
    cases["late_setup"] = {
        "scenario": late,
        "expected": expected("ENTRY_WINDOW_EXPIRED", "long"),
    }
    return cases


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "tests" / "data" / "replay"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in fixtures().items():
        content = dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        (output_dir / f"{name}.json").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
