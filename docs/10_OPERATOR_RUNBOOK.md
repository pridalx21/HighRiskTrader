# CATALYST operator runbook

## Safety boundary

CATALYST MVP is demo-only. Do not modify the adapter to accept real or unknown
account modes. Do not place passwords, terminal profiles, `.env` files, journal
databases, or broker logs in Git.

The persistent kill-switch path should live outside tracked source, for example:

```text
.runtime/kill-switch.json
```

The execution composition must wrap the verified MT5 adapter with
`GuardedDemoBroker` and use that guarded instance for `DurableDemoExecutor`.

## Installation

Core development and validation:

```bash
python -m pip install -e ".[dev]"
```

Windows MT5 + local dashboard dependencies:

```bash
python -m pip install -e ".[dev,mt5,ui]"
```

## Configure the real demo terminal locally

Provide environment values locally. Do not paste the password into chat or
commit it. The terminal should already have the demo credentials stored through
its normal local profile/login flow.

```text
CATALYST_MT5_TERMINAL_PATH=<absolute path to terminal64.exe>
CATALYST_MT5_LOGIN=<demo login id>
CATALYST_MT5_SERVER=<exact demo server>
CATALYST_MT5_SYMBOL_MAPPING_JSON={"US100":"<broker symbol>"}
CATALYST_MT5_ECONOMICS_JSON={"US100":{"commission_per_volume":"...","slippage_ticks":"...","profit_to_account_rate":"..."}}
```

Every configured logical symbol must appear in both JSON objects. Economics are
explicit because commission/slippage/conversion assumptions must not be guessed.

## First real-terminal check: shadow only

Run:

```bash
catalyst-mt5-shadow-smoke
```

The command verifies the configured terminal, login, server, explicit demo mode,
contract metadata, latest ticks, positions, and pending orders. It has automatic
execution disabled and does not call order submission. Success ends with:

```text
mt5_shadow_smoke=pass orders_sent=0
```

If it fails, keep the system disarmed. Correct mapping/economics/account state
before proceeding.

## Startup sequence

1. Confirm the persistent kill-switch latch state.
2. Load and validate the normal strategy/risk configuration.
3. Open `SQLiteJournal` and acquire the single-instance lock.
4. Create the MT5 demo adapter with explicit mapping/economics.
5. Wrap it in `GuardedDemoBroker` using the same persistent latch path.
6. Connect and positively verify demo mode, login, server, and connectivity.
7. Run restart reconciliation for every unresolved durable order intent.
8. Load the strict UTC event CSV and warm required market evidence.
9. Build the read-only dashboard snapshot from stored/observed state.
10. Start disarmed. Automatic demo execution requires an authenticated,
    confirmed control request against fresh state.

Do not arm if reconciliation is unresolved, the journal is unhealthy, market
state is stale, account mode is not positively demo, or the kill switch is
active.

## Arm / disarm

Arming flows only through `OperatorControlPlane.ARM_AUTO_DEMO`. It requires:

- matching local authentication token digest;
- explicit operator confirmation;
- fresh dashboard source timestamp;
- healthy audit journal;
- clear persistent kill switch;
- broker adapter's positive demo verification.

Disarm through `DISARM_AUTO_DEMO`. After restart, arming is never restored
automatically.

## Emergency kill switch

The fastest independent safety action is:

```bash
catalyst-kill-switch --path .runtime/kill-switch.json --reason "operator stop"
```

This only engages the latch. It cannot clear it. Because `GuardedDemoBroker`
checks the latch directly, new submissions remain blocked even if the dashboard
or normal disarm call is unavailable.

After an incident, investigate broker state and journal state first. Clear the
latch only through authenticated `ACKNOWLEDGE_INCIDENT`, while execution is
disarmed and the audit journal is healthy. A failed audit of the clear action
re-latches automatically.

## Disconnect / timeout / unknown order result

- Disarm immediately on disconnect or unreadable account state.
- Reconnect with bounded retries, then re-verify demo account/login/server.
- A send timeout or ambiguous result is `UNCERTAIN`.
- Never re-submit an uncertain intent.
- Run `RestartReconciler` against open orders and history.
- `NOT_FOUND`, `UNKNOWN`, or adapter errors remain disarmed for manual review.

## Shutdown

1. Disarm automatic demo execution.
2. Persist final heartbeat/state.
3. Reconcile managed demo orders/positions.
4. Apply the existing intraday close policy to any managed position.
5. Disconnect MT5 cleanly.
6. Close the journal and release its single-instance lock.
7. Leave the persistent kill switch engaged if shutdown was caused by an
   incident or unresolved broker state.

## Validation evidence pack

Run the frozen harness with real historical/demo observations:

```bash
catalyst-validate observations.json validation-output --strategy-version <frozen-version>
```

Review both `validation_report.json` and `validation_report.md`. The manifest
contains input/report hashes. `CONTINUE` is a research promotion gate only; it
does not enable real-money trading.

## Incident export

For a specific event, export the canonical event audit bundle from
`SQLiteJournal.export_event_audit_bundle`. Preserve the journal and source event
file before attempting repairs. Do not delete the lock file while another
CATALYST process may still be active.
