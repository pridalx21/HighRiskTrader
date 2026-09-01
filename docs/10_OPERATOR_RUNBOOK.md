# CATALYST operator runbook

## Safety boundary

CATALYST MVP is demo-only. Do not modify the adapter to accept real or unknown
account modes. Do not place passwords, terminal profiles, `.env` files, journal
databases, control tokens, or broker logs in Git.

The persistent runtime files should live outside tracked source, normally under
`.runtime/`:

```text
.runtime/kill-switch.json
.runtime/risk-state.json
.runtime/managed-positions.json
.runtime/events.csv
.runtime/live_runtime.json
.runtime/settings.demo.toml
```

The entry execution composition wraps the verified MT5 adapter with
`GuardedDemoBroker` and uses that guarded instance for `DurableDemoExecutor`.
Reduce-risk exits are handled separately by `MT5ExitAdapter` so disarming or
engaging the kill switch blocks new risk without blocking a required exit.

## Installation

```bash
python -m pip install -e ".[dev,mt5,ui]"
```

Verify the packaged runner:

```bash
catalyst-run --help
```

## Configure the real demo terminal locally

The terminal should already have the demo credentials stored through its normal
local profile/login flow. CATALYST does not need the password in an environment
variable.

```text
CATALYST_MT5_TERMINAL_PATH=<absolute path to terminal64.exe>
CATALYST_MT5_LOGIN=<demo login id>
CATALYST_MT5_SERVER=<exact demo server>
CATALYST_MT5_SYMBOL_MAPPING_JSON={"US100":"<broker symbol>",...}
CATALYST_MT5_ECONOMICS_JSON={"US100":{"commission_per_volume":"...","slippage_ticks":"...","profit_to_account_rate":"..."},...}
CATALYST_CONFIG_PATH=.runtime/settings.shadow.toml
CATALYST_LIVE_CONFIG=.runtime/live_runtime.json
CATALYST_EVENT_CSV=.runtime/events.csv
```

Every primary and related logical symbol must appear in the mapping/economics
objects. Commission, slippage, and conversion assumptions must not be guessed.

## First real-terminal check: shadow smoke

```bash
catalyst-mt5-shadow-smoke
```

Success ends with:

```text
mt5_shadow_smoke=pass orders_sent=0
```

If it fails, keep the system disarmed.

## Full runner preflight

```bash
catalyst-run --preflight-only
```

Preflight imports the strict event CSV into the journal, verifies the exact demo
account/login/server, creates the account snapshot, and runs restart
reconciliation. Any unresolved durable intent blocks normal startup.

## Continuous shadow mode

```bash
catalyst-run
```

Shadow mode uses live MT5 bid/ask data and the same deterministic feature and
decision pipeline as replay while the broker remains physically disarmed. It
never calls entry or exit order submission.

One cycle only:

```bash
catalyst-run --once
```

## Auto-demo mode

Auto-demo is intentionally multi-factor. The local TOML must contain:

```toml
[system]
demo_only = true
auto_demo_armed = true
```

The strict MVP execution section stays:

```toml
[execution]
mode = "shadow"
require_initial_stop = true
blind_order_retry = false
maximum_submit_attempts = 1
```

Then set local arming factors:

```text
CATALYST_AUTO_DEMO_CONFIRM=DEMO_ONLY
CATALYST_CONTROL_TOKEN=<local random token>
```

Start:

```bash
catalyst-run --auto-demo
```

Arming flows through `OperatorControlPlane.ARM_AUTO_DEMO` and still requires a
healthy journal, clear kill switch, fresh control state, positive MT5 demo
verification, and all normal strategy/risk gates. Restart never silently
restores an armed process.

## Entry lifecycle

For a green auto-demo trade plan:

1. persist the complete decision;
2. persist managed-position exit metadata;
3. reserve the durable idempotency key;
4. positively recheck demo mode/connectivity;
5. transition the intent to submitting;
6. call the broker exactly once;
7. include the mandatory server-side initial stop in the entry request;
8. persist acknowledgement/rejection/uncertain state.

A timeout or ambiguous result becomes uncertain. Do not retry it. Reconcile on
restart against MT5 orders/history.

## Managed intraday exits

`MT5ExitAdapter` recognizes only positions matching both this CATALYST magic
number and a deterministic `CAT-...` comment. Manual/unrelated positions are not
managed.

The runtime evaluates CATALYST positions before new entries on each auto-demo
cycle. Existing `IntradayExitEngine` rules cover:

- emergency exit if the protective stop is missing;
- protective-stop condition;
- full pre-event-range reclaim;
- configured session cutoff.

Exit requests reference the exact MT5 position ticket and send one opposite
market deal at the executable side. They do **not** require the entry arm latch,
because disarm/kill-switch must block adding risk without blocking risk
reduction.

Managed exit metadata is persisted at:

```text
.runtime/managed-positions.json
```

Do not edit/delete this file while a CATALYST position is open. If a tagged
CATALYST position is found without valid metadata, the runtime takes the
conservative reduce-risk close path rather than inventing an exit policy.

An ambiguous exit result is never blindly retried. A confirmed broker
acknowledgement is followed by a fresh positions read; if the same ticket still
exists, the runtime fails closed.

## Emergency kill switch

```bash
catalyst-kill-switch --path .runtime/kill-switch.json --reason "operator stop"
```

The latch blocks all new guarded entry submissions. Auto-demo may continue only
the reduce-risk management of already-open CATALYST positions. Do not manually
clear the latch during an unresolved incident.

Clear only through authenticated `ACKNOWLEDGE_INCIDENT` while execution is
disarmed and the audit journal is healthy. A failed audit of the clear operation
re-latches automatically.

## Disconnect / timeout / unknown order result

- Disarm on disconnect or unreadable account state.
- Reconnect with bounded retries and then re-verify demo account/login/server.
- Entry timeout/ambiguous result is `UNCERTAIN` and is never resubmitted.
- Restart reconciliation checks open orders and history.
- Unresolved reconciliation remains disarmed.
- Exit ambiguity also stops blind retries and requires broker-state inspection.

## Event and live-rule maintenance

The runner currently consumes strict local event CSV data; it does not download
the economic calendar automatically. Keep `.runtime/events.csv` current with
explicit UTC timestamps.

`live_runtime.json` supplies primary/related market rules and the intraday
session cutoff. Checked-in values are examples, not validated trading
parameters. Freeze and version any rule set used for meaningful validation.

## Shutdown

Normal operator shutdown is `Ctrl+C`. The runner then disarms, disconnects MT5,
closes the SQLite journal, and releases its lock.

Before shutting down the computer/terminal with managed positions open, confirm
that the runner has not been interrupted before its required intraday exit. If
broker state is ambiguous, engage the kill switch and investigate rather than
resending orders.

## Validation evidence pack

```bash
catalyst-validate observations.json validation-output --strategy-version <frozen-version>
```

Review `validation_report.json` and `validation_report.md`. `CONTINUE` is a
research/demo promotion gate only; it does not enable real-money trading.

## Incident export

For a specific event, export the canonical event audit bundle from
`SQLiteJournal.export_event_audit_bundle`. Preserve the journal, event file,
runtime position-state file, and relevant MT5 records before attempting repairs.
Do not delete the lock file while another CATALYST process may still be active.
