"""Strict standard-library TOML configuration for the deterministic core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tomllib import TOMLDecodeError, load
from typing import Any

from catalyst.domain.serialization import sha256_canonical
from catalyst.engine.state_machine import StateMachineConfig
from catalyst.risk.policy import RiskPolicy
from catalyst.strategy.event_reaction_retest import EventReactionRetestConfig


@dataclass(frozen=True, slots=True)
class SystemConfig:
    demo_only: bool = True
    timezone: str = "UTC"
    auto_demo_armed: bool = False
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.demo_only:
            raise ValueError("demo_only must be true")
        if self.timezone != "UTC":
            raise ValueError("timezone must equal UTC")
        if not self.log_level.strip():
            raise ValueError("log_level must not be empty")


@dataclass(frozen=True, slots=True)
class RiskConfig:
    policy: RiskPolicy = field(default_factory=RiskPolicy)
    monthly_fresh_capital_chf: Decimal = Decimal("1000.00")
    allow_averaging_down: bool = False
    allow_overnight: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.monthly_fresh_capital_chf, Decimal):
            raise ValueError("monthly_fresh_capital_chf must be Decimal")
        if not self.monthly_fresh_capital_chf.is_finite() or self.monthly_fresh_capital_chf <= 0:
            raise ValueError("monthly_fresh_capital_chf must be finite and positive")
        if self.allow_averaging_down:
            raise ValueError("allow_averaging_down must be false")
        if self.allow_overnight:
            raise ValueError("allow_overnight must be false")


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    mode: str = "shadow"
    require_initial_stop: bool = True
    blind_order_retry: bool = False
    maximum_submit_attempts: int = 1

    def __post_init__(self) -> None:
        if self.mode != "shadow":
            raise ValueError("Phase 1 execution mode must equal shadow")
        if not self.require_initial_stop:
            raise ValueError("require_initial_stop must be true")
        if self.blind_order_retry:
            raise ValueError("blind_order_retry must be false")
        if self.maximum_submit_attempts != 1:
            raise ValueError("maximum_submit_attempts must equal 1")


@dataclass(frozen=True, slots=True)
class StorageConfig:
    journal_path: str = "data/catalyst.sqlite3"
    raw_data_dir: str = "data/raw"
    derived_data_dir: str = "data/derived"

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.journal_path, self.raw_data_dir, self.derived_data_dir)
        ):
            raise ValueError("storage paths must not be empty")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    system: SystemConfig = field(default_factory=SystemConfig)
    strategy: EventReactionRetestConfig = field(default_factory=EventReactionRetestConfig)
    state_machine: StateMachineConfig = field(default_factory=StateMachineConfig)
    pre_event_range: timedelta = timedelta(minutes=30)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def __post_init__(self) -> None:
        if self.pre_event_range <= timedelta(0):
            raise ValueError("pre_event_range must be positive")
        if self.state_machine.shock_window != timedelta(seconds=self.strategy.shock_window_seconds):
            raise ValueError("strategy and state-machine shock windows must match")
        if self.state_machine.entry_deadline != timedelta(
            seconds=self.strategy.entry_deadline_seconds
        ):
            raise ValueError("strategy and state-machine entry deadlines must match")

    @property
    def configuration_hash(self) -> str:
        decision_config = {
            "system": {
                "demo_only": self.system.demo_only,
                "timezone": self.system.timezone,
                "auto_demo_armed": self.system.auto_demo_armed,
            },
            "strategy": self.strategy,
            "state_machine": self.state_machine,
            "pre_event_range": self.pre_event_range,
            "risk": self.risk,
            "execution": self.execution,
        }
        return sha256_canonical(decision_config)


def _require_table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a TOML table")
    return value


def _require_exact_keys(data: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(data)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ValueError(f"{context} is missing keys: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{context} has unknown keys: {', '.join(unknown)}")


def _require_type(data: Mapping[str, Any], key: str, expected: type, context: str) -> Any:
    value = data[key]
    if type(value) is not expected:
        raise ValueError(f"{context}.{key} must be {expected.__name__}")
    return value


def _decimal_string(data: Mapping[str, Any], key: str, context: str) -> Decimal:
    raw = _require_type(data, key, str, context)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{context}.{key} must be a decimal string") from exc
    if not value.is_finite():
        raise ValueError(f"{context}.{key} must be finite")
    return value


def parse_runtime_config(data: Mapping[str, Any]) -> RuntimeConfig:
    """Parse an already-decoded TOML mapping using an exact fail-closed schema."""

    _require_exact_keys(data, {"system", "strategy", "risk", "execution", "storage"}, "root")
    system_data = _require_table(data, "system")
    strategy_data = _require_table(data, "strategy")
    risk_data = _require_table(data, "risk")
    execution_data = _require_table(data, "execution")
    storage_data = _require_table(data, "storage")

    _require_exact_keys(
        system_data,
        {"demo_only", "timezone", "auto_demo_armed", "log_level"},
        "system",
    )
    _require_exact_keys(
        strategy_data,
        {
            "strategy_id",
            "pre_arm_minutes",
            "pre_event_range_minutes",
            "shock_window_seconds",
            "entry_deadline_minutes",
            "minimum_related_markets",
            "minimum_confirmations",
            "maximum_spread_multiple",
            "maximum_data_age_seconds",
        },
        "strategy",
    )
    _require_exact_keys(
        risk_data,
        {
            "risk_fraction",
            "maximum_daily_loss_r",
            "maximum_consecutive_losses",
            "maximum_active_risk_clusters",
            "monthly_fresh_capital_chf",
            "allow_averaging_down",
            "allow_overnight",
        },
        "risk",
    )
    _require_exact_keys(
        execution_data,
        {"mode", "require_initial_stop", "blind_order_retry", "maximum_submit_attempts"},
        "execution",
    )
    _require_exact_keys(
        storage_data,
        {"journal_path", "raw_data_dir", "derived_data_dir"},
        "storage",
    )

    system = SystemConfig(
        demo_only=_require_type(system_data, "demo_only", bool, "system"),
        timezone=_require_type(system_data, "timezone", str, "system"),
        auto_demo_armed=_require_type(system_data, "auto_demo_armed", bool, "system"),
        log_level=_require_type(system_data, "log_level", str, "system"),
    )
    shock_window_seconds = _require_type(strategy_data, "shock_window_seconds", int, "strategy")
    entry_deadline_minutes = _require_type(strategy_data, "entry_deadline_minutes", int, "strategy")
    strategy = EventReactionRetestConfig(
        strategy_id=_require_type(strategy_data, "strategy_id", str, "strategy"),
        shock_window_seconds=shock_window_seconds,
        entry_deadline_seconds=entry_deadline_minutes * 60,
        minimum_related_markets=_require_type(
            strategy_data, "minimum_related_markets", int, "strategy"
        ),
        minimum_confirmations=_require_type(
            strategy_data, "minimum_confirmations", int, "strategy"
        ),
        maximum_spread_multiple=_decimal_string(
            strategy_data, "maximum_spread_multiple", "strategy"
        ),
        maximum_data_age_seconds=_decimal_string(
            strategy_data, "maximum_data_age_seconds", "strategy"
        ),
    )
    state_machine = StateMachineConfig(
        pre_arm=timedelta(minutes=_require_type(strategy_data, "pre_arm_minutes", int, "strategy")),
        shock_window=timedelta(seconds=shock_window_seconds),
        entry_deadline=timedelta(minutes=entry_deadline_minutes),
    )
    risk = RiskConfig(
        policy=RiskPolicy(
            risk_fraction=_decimal_string(risk_data, "risk_fraction", "risk"),
            maximum_daily_loss_r=_decimal_string(risk_data, "maximum_daily_loss_r", "risk"),
            maximum_consecutive_losses=_require_type(
                risk_data, "maximum_consecutive_losses", int, "risk"
            ),
            maximum_active_risk_clusters=_require_type(
                risk_data, "maximum_active_risk_clusters", int, "risk"
            ),
        ),
        monthly_fresh_capital_chf=_decimal_string(risk_data, "monthly_fresh_capital_chf", "risk"),
        allow_averaging_down=_require_type(risk_data, "allow_averaging_down", bool, "risk"),
        allow_overnight=_require_type(risk_data, "allow_overnight", bool, "risk"),
    )
    execution = ExecutionConfig(
        mode=_require_type(execution_data, "mode", str, "execution"),
        require_initial_stop=_require_type(
            execution_data, "require_initial_stop", bool, "execution"
        ),
        blind_order_retry=_require_type(execution_data, "blind_order_retry", bool, "execution"),
        maximum_submit_attempts=_require_type(
            execution_data, "maximum_submit_attempts", int, "execution"
        ),
    )
    storage = StorageConfig(
        journal_path=_require_type(storage_data, "journal_path", str, "storage"),
        raw_data_dir=_require_type(storage_data, "raw_data_dir", str, "storage"),
        derived_data_dir=_require_type(storage_data, "derived_data_dir", str, "storage"),
    )
    return RuntimeConfig(
        system=system,
        strategy=strategy,
        state_machine=state_machine,
        pre_event_range=timedelta(
            minutes=_require_type(
                strategy_data,
                "pre_event_range_minutes",
                int,
                "strategy",
            )
        ),
        risk=risk,
        execution=execution,
        storage=storage,
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    """Load and validate one TOML configuration file."""

    config_path = Path(path)
    try:
        with config_path.open("rb") as handle:
            data = load(handle)
    except TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML configuration: {exc}") from exc
    return parse_runtime_config(data)
