"""Strict JSON boundary for deterministic replay fixtures."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError, load
from pathlib import Path
from typing import Any, Mapping

from catalyst.domain.enums import AccountMode, Direction, EventImportance, EventStatus
from catalyst.domain.models import AccountSnapshot, BrokerContract, EconomicEvent
from catalyst.replay.models import (
    CrossAssetRule,
    ExecutionScenario,
    ExecutionStatus,
    ExpectedOutcome,
    RawBar,
    RawTick,
    ReplayFixture,
    ReplayScenario,
    require_utc,
)


def _keys(data: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(data)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ValueError(f"{context} is missing keys: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{context} has unknown keys: {', '.join(unknown)}")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _string(data: Mapping[str, Any], key: str, context: str) -> str:
    value = data[key]
    if type(value) is not str or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, Any], key: str, context: str) -> int:
    value = data[key]
    if type(value) is not int:
        raise ValueError(f"{context}.{key} must be an integer")
    return value


def _boolean(data: Mapping[str, Any], key: str, context: str) -> bool:
    value = data[key]
    if type(value) is not bool:
        raise ValueError(f"{context}.{key} must be boolean")
    return value


def _decimal(data: Mapping[str, Any], key: str, context: str) -> Decimal:
    raw = _string(data, key, context)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{context}.{key} must be a decimal string") from exc
    if not value.is_finite():
        raise ValueError(f"{context}.{key} must be finite")
    return value


def _timestamp(data: Mapping[str, Any], key: str, context: str) -> datetime:
    raw = _string(data, key, context)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context}.{key} must be an ISO timestamp") from exc
    require_utc(value, f"{context}.{key}")
    return value


def _optional_string(data: Mapping[str, Any], key: str, context: str) -> str | None:
    value = data[key]
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError(f"{context}.{key} must be null or a non-empty string")
    return value


def _event(data: Mapping[str, Any]) -> EconomicEvent:
    expected = {
        "event_id",
        "name",
        "scheduled_at",
        "ingested_at",
        "currency",
        "importance",
        "status",
        "eligible_symbols",
        "source",
    }
    _keys(data, expected, "event")
    eligible = tuple(
        value
        for value in _list(data["eligible_symbols"], "event.eligible_symbols")
        if type(value) is str
    )
    if len(eligible) != len(data["eligible_symbols"]):
        raise ValueError("event.eligible_symbols must contain only strings")
    try:
        importance = EventImportance(_string(data, "importance", "event").lower())
        status = EventStatus(_string(data, "status", "event").lower())
    except ValueError as exc:
        raise ValueError("event has an unknown importance or status") from exc
    return EconomicEvent(
        event_id=_string(data, "event_id", "event"),
        name=_string(data, "name", "event"),
        scheduled_at=_timestamp(data, "scheduled_at", "event"),
        ingested_at=_timestamp(data, "ingested_at", "event"),
        currency=_string(data, "currency", "event"),
        importance=importance,
        status=status,
        eligible_symbols=eligible,
        source=_string(data, "source", "event"),
    )


def _account(data: Mapping[str, Any]) -> AccountSnapshot:
    expected = {
        "mode",
        "currency",
        "balance",
        "equity",
        "day_start_equity",
        "month_start_equity",
        "daily_realized_pnl",
        "consecutive_losses",
        "active_risk_clusters",
        "open_worst_case_risk",
        "timestamp",
        "connected",
    }
    _keys(data, expected, "account")
    try:
        mode = AccountMode(_string(data, "mode", "account").lower())
    except ValueError as exc:
        raise ValueError("account.mode is unknown") from exc
    return AccountSnapshot(
        mode=mode,
        currency=_string(data, "currency", "account"),
        balance=_decimal(data, "balance", "account"),
        equity=_decimal(data, "equity", "account"),
        day_start_equity=_decimal(data, "day_start_equity", "account"),
        month_start_equity=_decimal(data, "month_start_equity", "account"),
        daily_realized_pnl=_decimal(data, "daily_realized_pnl", "account"),
        consecutive_losses=_integer(data, "consecutive_losses", "account"),
        active_risk_clusters=_integer(data, "active_risk_clusters", "account"),
        open_worst_case_risk=_decimal(data, "open_worst_case_risk", "account"),
        timestamp=_timestamp(data, "timestamp", "account"),
        connected=_boolean(data, "connected", "account"),
    )


def _contract(data: Mapping[str, Any]) -> BrokerContract:
    expected = {
        "symbol",
        "tick_size",
        "tick_value",
        "contract_size",
        "profit_currency",
        "account_currency",
        "profit_to_account_rate",
        "volume_minimum",
        "volume_maximum",
        "volume_step",
        "commission_per_volume",
        "slippage_ticks",
    }
    _keys(data, expected, "contract")
    return BrokerContract(
        symbol=_string(data, "symbol", "contract"),
        tick_size=_decimal(data, "tick_size", "contract"),
        tick_value=_decimal(data, "tick_value", "contract"),
        contract_size=_decimal(data, "contract_size", "contract"),
        profit_currency=_string(data, "profit_currency", "contract"),
        account_currency=_string(data, "account_currency", "contract"),
        profit_to_account_rate=_decimal(data, "profit_to_account_rate", "contract"),
        volume_minimum=_decimal(data, "volume_minimum", "contract"),
        volume_maximum=_decimal(data, "volume_maximum", "contract"),
        volume_step=_decimal(data, "volume_step", "contract"),
        commission_per_volume=_decimal(data, "commission_per_volume", "contract"),
        slippage_ticks=_decimal(data, "slippage_ticks", "contract"),
    )


def _tick(data: Mapping[str, Any], index: int) -> RawTick:
    context = f"ticks[{index}]"
    _keys(data, {"symbol", "timestamp", "bid", "ask", "source_sequence"}, context)
    return RawTick(
        symbol=_string(data, "symbol", context),
        timestamp=_timestamp(data, "timestamp", context),
        bid=_decimal(data, "bid", context),
        ask=_decimal(data, "ask", context),
        source_sequence=_integer(data, "source_sequence", context),
    )


def _bar(data: Mapping[str, Any], index: int) -> RawBar:
    context = f"bars[{index}]"
    expected = {
        "symbol",
        "opened_at",
        "closed_at",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "source_sequence",
    }
    _keys(data, expected, context)
    return RawBar(
        symbol=_string(data, "symbol", context),
        opened_at=_timestamp(data, "opened_at", context),
        closed_at=_timestamp(data, "closed_at", context),
        bid_open=_decimal(data, "bid_open", context),
        bid_high=_decimal(data, "bid_high", context),
        bid_low=_decimal(data, "bid_low", context),
        bid_close=_decimal(data, "bid_close", context),
        ask_open=_decimal(data, "ask_open", context),
        ask_high=_decimal(data, "ask_high", context),
        ask_low=_decimal(data, "ask_low", context),
        ask_close=_decimal(data, "ask_close", context),
        source_sequence=_integer(data, "source_sequence", context),
    )


def parse_replay_fixture(data: Mapping[str, Any]) -> ReplayFixture:
    """Parse a normalized fixture mapping and reject unknown or missing data."""

    _keys(data, {"scenario", "expected"}, "root")
    scenario_data = _mapping(data["scenario"], "scenario")
    expected_scenario_keys = {
        "scenario_id",
        "event",
        "primary_symbol",
        "ticks",
        "bars",
        "related_rules",
        "account",
        "contract",
        "execution",
        "evaluation_delay_seconds",
        "session_cutoff",
        "market_open",
        "emergency_exit",
    }
    _keys(scenario_data, expected_scenario_keys, "scenario")
    rules = []
    for index, raw_rule in enumerate(_list(scenario_data["related_rules"], "related_rules")):
        rule = _mapping(raw_rule, f"related_rules[{index}]")
        _keys(rule, {"symbol", "polarity", "minimum_move"}, f"related_rules[{index}]")
        rules.append(
            CrossAssetRule(
                symbol=_string(rule, "symbol", f"related_rules[{index}]"),
                polarity=_integer(rule, "polarity", f"related_rules[{index}]"),
                minimum_move=_decimal(rule, "minimum_move", f"related_rules[{index}]"),
            )
        )
    execution_data = _mapping(scenario_data["execution"], "execution")
    _keys(
        execution_data,
        {
            "latency_milliseconds",
            "maximum_adverse_slippage_ticks",
            "fill_fraction",
            "rejection_code",
        },
        "execution",
    )
    scenario = ReplayScenario(
        scenario_id=_string(scenario_data, "scenario_id", "scenario"),
        event=_event(_mapping(scenario_data["event"], "event")),
        primary_symbol=_string(scenario_data, "primary_symbol", "scenario"),
        ticks=tuple(
            _tick(_mapping(item, f"ticks[{index}]"), index)
            for index, item in enumerate(_list(scenario_data["ticks"], "ticks"))
        ),
        bars=tuple(
            _bar(_mapping(item, f"bars[{index}]"), index)
            for index, item in enumerate(_list(scenario_data["bars"], "bars"))
        ),
        related_rules=tuple(rules),
        account=_account(_mapping(scenario_data["account"], "account")),
        contract=_contract(_mapping(scenario_data["contract"], "contract")),
        execution=ExecutionScenario(
            latency_milliseconds=_integer(
                execution_data,
                "latency_milliseconds",
                "execution",
            ),
            maximum_adverse_slippage_ticks=_decimal(
                execution_data,
                "maximum_adverse_slippage_ticks",
                "execution",
            ),
            fill_fraction=_decimal(execution_data, "fill_fraction", "execution"),
            rejection_code=_optional_string(execution_data, "rejection_code", "execution"),
        ),
        evaluation_delay_seconds=_decimal(
            scenario_data,
            "evaluation_delay_seconds",
            "scenario",
        ),
        session_cutoff=_timestamp(scenario_data, "session_cutoff", "scenario"),
        market_open=_boolean(scenario_data, "market_open", "scenario"),
        emergency_exit=_boolean(scenario_data, "emergency_exit", "scenario"),
    )
    expected_data = _mapping(data["expected"], "expected")
    _keys(
        expected_data,
        {"decision_code", "direction", "execution_status", "exit_reason"},
        "expected",
    )
    raw_direction = _optional_string(expected_data, "direction", "expected")
    raw_execution = _optional_string(expected_data, "execution_status", "expected")
    try:
        direction = Direction(raw_direction) if raw_direction is not None else None
        execution_status = (
            ExecutionStatus(raw_execution) if raw_execution is not None else None
        )
    except ValueError as exc:
        raise ValueError("expected has an unknown direction or execution status") from exc
    expected = ExpectedOutcome(
        decision_code=_string(expected_data, "decision_code", "expected"),
        direction=direction,
        execution_status=execution_status,
        exit_reason=_optional_string(expected_data, "exit_reason", "expected"),
    )
    return ReplayFixture(scenario=scenario, expected=expected)


def load_replay_fixture(path: str | Path) -> ReplayFixture:
    """Load one strict replay fixture from JSON."""

    fixture_path = Path(path)
    try:
        with fixture_path.open("r", encoding="utf-8") as handle:
            raw = load(handle)
    except JSONDecodeError as exc:
        raise ValueError(f"invalid replay fixture JSON: {exc}") from exc
    return parse_replay_fixture(_mapping(raw, "root"))
