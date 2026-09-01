"""Windows MT5 demo runtime entry point.

The command supports two modes:

- default shadow: evaluate live events and write audit evidence, never submit;
- --auto-demo: explicitly arm the verified demo broker and allow durable
  at-most-once demo submissions.

There is intentionally no live-account mode.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from json import dumps, loads
from pathlib import Path
from time import sleep
from typing import Any

from catalyst.adapters.csv_event_feed import CsvEventFeed
from catalyst.adapters.guarded_demo_broker import GuardedDemoBroker
from catalyst.adapters.mt5_broker import MT5AccountRiskState, MT5DemoBroker, MT5DemoConfig
from catalyst.adapters.mt5_observability import MT5ReadAdapter
from catalyst.adapters.sqlite_journal import SQLiteJournal
from catalyst.config import RuntimeConfig, load_runtime_config
from catalyst.controls import ControlCommand, LocalKillSwitch, OperatorControlPlane
from catalyst.engine.reconciliation import RestartReconciler
from catalyst.mt5_shadow_smoke import _economics, _mapping
from catalyst.runtime import CatalystRuntime, LiveRuntimeConfig, load_live_runtime_config, utc_now

SOFTWARE_VERSION = "catalyst-mvp-0.1.0-runtime"
AUTO_DEMO_CONFIRMATION = "DEMO_ONLY"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


@dataclass(slots=True)
class RuntimeRiskTracker:
    """Persist session/month anchors and conservatively include open positions."""

    path: Path
    day_start_equity: Decimal | None = None
    month_start_equity: Decimal | None = None
    broker: MT5DemoBroker | None = None
    read: MT5ReadAdapter | None = None

    def initialize(self, *, equity: Decimal, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
            raise ValueError("risk tracker initialization requires UTC")
        day_key = now.date().isoformat()
        month_key = f"{now.year:04d}-{now.month:02d}"
        stored: dict[str, Any] = {}
        if self.path.exists():
            try:
                value = loads(self.path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    stored = value
            except (OSError, ValueError):
                stored = {}
        stored_day = stored.get("day")
        stored_month = stored.get("month")
        try:
            day_start = (
                Decimal(str(stored["day_start_equity"]))
                if stored_day == day_key
                else equity
            )
            month_start = (
                Decimal(str(stored["month_start_equity"]))
                if stored_month == month_key
                else equity
            )
        except (KeyError, ValueError):
            day_start = equity
            month_start = equity
        if day_start <= 0 or month_start <= 0:
            day_start = equity
            month_start = equity
        self.day_start_equity = day_start
        self.month_start_equity = month_start
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            dumps(
                {
                    "day": day_key,
                    "day_start_equity": str(day_start),
                    "month": month_key,
                    "month_start_equity": str(month_start),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    def attach(self, broker: MT5DemoBroker, read: MT5ReadAdapter) -> None:
        self.broker = broker
        self.read = read

    def __call__(self) -> MT5AccountRiskState:
        if self.day_start_equity is None or self.month_start_equity is None:
            raise RuntimeError("runtime risk tracker has not been initialized")
        current_equity = self.day_start_equity
        if self.broker is not None:
            account = self.broker._verify_demo_account()
            current_equity = Decimal(str(getattr(account, "equity", self.day_start_equity)))
        position_count = len(self.read.positions()) if self.read is not None else 0
        return MT5AccountRiskState(
            day_start_equity=self.day_start_equity,
            month_start_equity=self.month_start_equity,
            daily_realized_pnl=current_equity - self.day_start_equity,
            consecutive_losses=0,
            active_risk_clusters=position_count,
            open_worst_case_risk=Decimal("0"),
        )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run CATALYST against a verified MT5 demo account"
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("CATALYST_CONFIG_PATH", "config/settings.example.toml"),
        help="strict strategy/risk TOML",
    )
    parser.add_argument(
        "--live-config",
        default=os.environ.get("CATALYST_LIVE_CONFIG", "config/live_runtime.example.json"),
        help="explicit live primary/related-market JSON",
    )
    parser.add_argument(
        "--events",
        default=os.environ.get("CATALYST_EVENT_CSV", "config/events.example.csv"),
        help="strict UTC manual event CSV",
    )
    parser.add_argument(
        "--auto-demo",
        action="store_true",
        help="allow demo orders after explicit arm",
    )
    parser.add_argument("--once", action="store_true", help="run one polling cycle and exit")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="connect, verify demo account, reconcile, then exit without evaluating events",
    )
    return parser


def _mt5_config(*, auto_demo: bool) -> MT5DemoConfig:
    return MT5DemoConfig(
        terminal_path=Path(_required_environment("CATALYST_MT5_TERMINAL_PATH")),
        login=int(_required_environment("CATALYST_MT5_LOGIN")),
        server=_required_environment("CATALYST_MT5_SERVER"),
        symbol_mapping=_mapping(_required_environment("CATALYST_MT5_SYMBOL_MAPPING_JSON")),
        symbol_economics=_economics(_required_environment("CATALYST_MT5_ECONOMICS_JSON")),
        auto_execution_enabled=auto_demo,
    )


def _validate_auto_demo(config: RuntimeConfig) -> str:
    if not config.system.auto_demo_armed:
        raise RuntimeError(
            "--auto-demo requires system.auto_demo_armed=true in the hashed TOML configuration"
        )
    confirmation = _required_environment("CATALYST_AUTO_DEMO_CONFIRM")
    if confirmation != AUTO_DEMO_CONFIRMATION:
        raise RuntimeError(
            f"CATALYST_AUTO_DEMO_CONFIRM must equal {AUTO_DEMO_CONFIRMATION!r}"
        )
    return _required_environment("CATALYST_CONTROL_TOKEN")


def _print_cycle(results: tuple[Any, ...], *, now: datetime) -> None:
    if not results:
        print(f"{now.isoformat()} state=idle active_event_setups=0")
        return
    for result in results:
        if result.error is not None:
            print(
                f"{now.isoformat()} event={result.event_id} symbol={result.symbol} "
                f"state=error detail={result.error}"
            )
            continue
        assert result.decision is not None
        submission = result.submission
        suffix = ""
        if submission is not None:
            suffix = (
                f" submit_code={submission.code} accepted={str(submission.accepted).lower()}"
            )
        print(
            f"{now.isoformat()} event={result.event_id} symbol={result.symbol} "
            f"state={result.decision.state.value} code={result.decision.code}{suffix}"
        )


def _engage_on_uncertain(
    results: tuple[Any, ...],
    *,
    kill_switch: LocalKillSwitch,
    broker: GuardedDemoBroker,
    now: datetime,
) -> bool:
    unsafe = any(
        result.error is not None
        or (result.submission is not None and result.submission.requires_reconciliation)
        for result in results
    )
    if unsafe:
        broker.disarm()
        kill_switch.engage(occurred_at=now, reason="runtime error or uncertain demo order outcome")
        print("kill_switch=engaged runtime=stopped")
    return unsafe


def main() -> None:
    args = _argument_parser().parse_args()
    config = load_runtime_config(args.config)
    live_config: LiveRuntimeConfig = load_live_runtime_config(args.live_config)
    auto_demo = bool(args.auto_demo)
    control_token = _validate_auto_demo(config) if auto_demo else None

    now = utc_now()
    feed = CsvEventFeed.load(args.events, ingested_at=now)
    kill_switch = LocalKillSwitch(
        os.environ.get("CATALYST_KILL_SWITCH_PATH", ".runtime/kill-switch.json")
    )
    risk_tracker = RuntimeRiskTracker(
        Path(os.environ.get("CATALYST_RISK_STATE_PATH", ".runtime/risk-state.json"))
    )
    mt5 = MT5DemoBroker(_mt5_config(auto_demo=auto_demo), risk_tracker)
    read = MT5ReadAdapter(mt5)
    journal = SQLiteJournal.open(config.storage.journal_path, software_version=SOFTWARE_VERSION)
    guarded = GuardedDemoBroker(mt5, kill_switch)
    controls: OperatorControlPlane | None = None

    try:
        for record in feed.records:
            journal.record_event(record)
        mt5.connect()
        raw_account = mt5._verify_demo_account()
        equity = Decimal(str(getattr(raw_account, "equity", "0")))
        if not equity.is_finite() or equity <= 0:
            raise RuntimeError("verified MT5 demo equity must be positive")
        risk_tracker.initialize(equity=equity, now=now)
        risk_tracker.attach(mt5, read)

        reconciliation = RestartReconciler(journal, guarded).reconcile(occurred_at=now)
        if reconciliation.unresolved_idempotency_keys:
            raise RuntimeError(
                "unresolved durable order intents block startup: "
                + ",".join(reconciliation.unresolved_idempotency_keys)
            )

        account = guarded.account_snapshot()
        print(
            f"preflight=pass mode=demo login={mt5.config.login} server={mt5.config.server} "
            f"balance={account.balance} equity={account.equity}"
        )
        if args.preflight_only:
            print("runtime=preflight_complete orders_sent=0")
            return

        if auto_demo:
            assert control_token is not None
            controls = OperatorControlPlane(
                execution=guarded,
                audit=journal,
                kill_switch=kill_switch,
                authentication_digest=OperatorControlPlane.digest_token(control_token),
            )
            arm_at = utc_now()
            arm_result = controls.execute(
                ControlCommand.ARM_AUTO_DEMO,
                token=control_token,
                confirmed=True,
                occurred_at=arm_at,
                dashboard_source_at=arm_at,
                reason="catalyst-run explicit demo-auto startup",
            )
            if not arm_result.accepted:
                raise RuntimeError(
                    f"demo-auto arm failed: {arm_result.code}: {arm_result.message}"
                )
            print("runtime_mode=demo_auto armed=true")
        else:
            print("runtime_mode=shadow armed=false orders_sent=0")

        runtime = CatalystRuntime(
            config=config,
            live_config=live_config,
            journal=journal,
            broker=guarded,
            market_data=read,
            events=tuple(record.event for record in feed.records),
            auto_demo=auto_demo,
        )
        while True:
            cycle_at = utc_now()
            results = runtime.cycle(now=cycle_at)
            _print_cycle(results, now=cycle_at)
            if auto_demo and _engage_on_uncertain(
                results,
                kill_switch=kill_switch,
                broker=guarded,
                now=cycle_at,
            ):
                raise RuntimeError("runtime stopped fail-closed after unsafe broker/runtime state")
            if args.once:
                break
            sleep(float(live_config.poll_seconds))
    except KeyboardInterrupt:
        print("runtime=keyboard_interrupt")
    finally:
        shutdown_at = utc_now()
        try:
            if controls is not None and control_token is not None:
                controls.execute(
                    ControlCommand.DISARM_AUTO_DEMO,
                    token=control_token,
                    confirmed=True,
                    occurred_at=shutdown_at,
                    dashboard_source_at=shutdown_at,
                    reason="catalyst-run shutdown",
                )
            else:
                guarded.disarm()
        finally:
            mt5.disconnect()
            journal.close()
        print("runtime=stopped armed=false")


if __name__ == "__main__":
    main()
