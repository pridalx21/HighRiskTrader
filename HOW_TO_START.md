# CATALYST — How to start on an MT5 demo account

This guide describes the supported Windows startup path for the CATALYST MVP.

> **Safety boundary:** CATALYST is demo-only. Never use a real-money MT5 account with this MVP. The adapter positively verifies MT5 demo mode and fails closed if account mode, login, server, connectivity, market data, journal state, or reconciliation cannot be verified.

## 1. What you need

- Windows 10/11
- Python 3.11+
- Git
- MetaTrader 5 installed
- a dedicated **MT5 demo account**
- the demo account already logged in successfully in the normal MT5 terminal
- the HighRiskTrader repository

Recommended: use a demo balance close to the intended test capital, for example CHF 1,000.

Do **not** store the MT5 password in Git or paste it into chat. CATALYST uses the login already stored in the local MT5 terminal profile.

---

## 2. Clone or update the repository

Open PowerShell:

```powershell
git clone https://github.com/pridalx21/HighRiskTrader.git
cd HighRiskTrader
```

If the repository already exists:

```powershell
cd HighRiskTrader
git switch main
git pull origin main
```

---

## 3. Create a Python environment

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,mt5,ui]"
```

Check that the MT5 Python package imports:

```powershell
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
```

Check that the runner is installed:

```powershell
catalyst-run --help
```

---

## 4. Verify CATALYST before connecting to MT5

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

For the full release checks:

```powershell
ruff check .
ruff format --check .
mypy src
pytest --cov=catalyst --cov-report=term-missing
python scripts/release_verify.py
```

Do not continue if these checks fail.

---

## 5. Prepare the MT5 demo account

1. Start MetaTrader 5 manually.
2. Log in to the **demo** account.
3. Confirm that prices are updating.
4. Note the demo login number and exact server name.
5. Confirm that MT5 identifies the account as a demo account.
6. Find the exact `terminal64.exe` path, for example:

```text
C:\Program Files\MetaTrader 5\terminal64.exe
```

### Find the broker symbol names

CATALYST uses logical names such as `US100`, `US500`, `XAUUSD`, `EURUSD`, `USDJPY`, `USDCHF`, and `GER40`. Your broker may use names such as `USTEC`, `NAS100`, `US500.cash`, or `XAUUSD.a`.

Open **Market Watch** in MT5 and record the exact broker symbol for every primary **and every related market** used by the runtime configuration. Do not guess symbol names.

---

## 6. Set the MT5 variables in PowerShell

These variables exist only in the current PowerShell process:

```powershell
$env:CATALYST_MT5_TERMINAL_PATH = "C:\Program Files\MetaTrader 5\terminal64.exe"
$env:CATALYST_MT5_LOGIN = "12345678"
$env:CATALYST_MT5_SERVER = "YourBroker-Demo"
```

Configure logical-to-broker symbols. Example only:

```powershell
$env:CATALYST_MT5_SYMBOL_MAPPING_JSON = '{"US100":"USTEC","US500":"US500","USDJPY":"USDJPY"}'
```

Every mapped logical symbol also needs explicit execution economics:

```powershell
$env:CATALYST_MT5_ECONOMICS_JSON = '{"US100":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"US500":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"USDJPY":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"}}'
```

**The numbers above are placeholders, not broker facts.** Obtain realistic commission assumptions from the broker, use a pessimistic slippage allowance, and use the correct profit-currency-to-account-currency conversion rate. CATALYST rejects incomplete mappings/economics.

---

## 7. Run the real MT5 shadow smoke test

With MT5 running and the variables configured:

```powershell
catalyst-mt5-shadow-smoke
```

Expected successful ending:

```text
mt5_shadow_smoke=pass orders_sent=0
```

This verifies terminal connection, login, server, demo mode, symbol mapping, contract metadata, fresh bid/ask ticks, positions, and pending orders. It **does not send an order**.

If it fails, stop here.

---

## 8. Create local runtime files

Keep mutable runtime files under `.runtime` rather than changing checked-in examples:

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
Copy-Item config\live_runtime.example.json .runtime\live_runtime.json
Copy-Item config\events.example.csv .runtime\events.csv
Copy-Item config\settings.example.toml .runtime\settings.shadow.toml
```

### 8.1 Live cross-asset configuration

Edit:

```text
.runtime/live_runtime.json
```

It defines:

- polling interval
- bar aggregation interval
- intraday session cutoff after each event
- primary instruments
- related-market confirmation rules
- polarity
- minimum related-market move

The checked-in thresholds are **examples**, not validated production parameters. Every symbol referenced here must also exist in `CATALYST_MT5_SYMBOL_MAPPING_JSON` and `CATALYST_MT5_ECONOMICS_JSON`.

### 8.2 Event CSV

Edit:

```text
.runtime/events.csv
```

The checked-in file contains synthetic 2030 events and must not be used for current demo operation.

Schema:

```text
event_id,name,scheduled_at,currency,importance,status,eligible_symbols,source,actual,consensus,previous
```

Times must be explicit UTC, for example:

```text
2026-09-03T12:30:00+00:00
```

Logical symbols are separated with `|`:

```text
US100|US500|XAUUSD|EURUSD|USDJPY|USDCHF
```

The MVP does **not** yet download the economic calendar automatically. Update this local CSV with the real upcoming high-impact events you want to observe. If no current eligible event is present, the runner correctly remains idle.

---

## 9. Run the full preflight

Point CATALYST at the local files:

```powershell
$env:CATALYST_CONFIG_PATH = ".runtime/settings.shadow.toml"
$env:CATALYST_LIVE_CONFIG = ".runtime/live_runtime.json"
$env:CATALYST_EVENT_CSV = ".runtime/events.csv"
```

Run:

```powershell
catalyst-run --preflight-only
```

A successful preflight positively verifies the demo account, imports the event file into the durable journal, checks the account snapshot, and performs restart reconciliation. It exits without evaluating or submitting trades.

Do not proceed if reconciliation reports unresolved order intents.

---

## 10. Start continuous Shadow Mode first

Run:

```powershell
catalyst-run
```

Shadow mode:

- continuously reads real MT5 bid/ask data;
- evaluates current eligible events;
- uses the same deterministic feature builder and `DecisionPipeline` as replay;
- journals decisions;
- prints current state/reason codes;
- keeps the broker physically disarmed;
- sends **zero entry or exit orders**.

Typical idle output is expected when no configured event is active.

For a single cycle only:

```powershell
catalyst-run --once
```

Run Shadow Mode through several real events before enabling automatic demo orders.

Stop the runner with `Ctrl+C`.

---

## 11. Enable automatic **demo-only** execution

Do this only after Shadow Mode and preflight work correctly.

Create a separate local config:

```powershell
Copy-Item .runtime\settings.shadow.toml .runtime\settings.demo.toml
```

Edit `.runtime/settings.demo.toml` and change only:

```toml
[system]
auto_demo_armed = true
```

Keep these safeguards unchanged:

```toml
demo_only = true
```

```toml
[risk]
allow_averaging_down = false
allow_overnight = false
```

```toml
[execution]
mode = "shadow"
require_initial_stop = true
blind_order_retry = false
maximum_submit_attempts = 1
```

`execution.mode = "shadow"` remains part of the strict MVP config contract; the separate `--auto-demo` flag and explicit runtime arming control whether the verified demo adapter may submit.

Set the demo config and the additional local arming factors:

```powershell
$env:CATALYST_CONFIG_PATH = ".runtime/settings.demo.toml"
$env:CATALYST_AUTO_DEMO_CONFIRM = "DEMO_ONLY"
$env:CATALYST_CONTROL_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Do not print, commit, or share the control token unnecessarily.

Start automatic demo execution:

```powershell
catalyst-run --auto-demo
```

Auto-demo requires **all** of the following:

- positively verified MT5 demo account;
- exact configured login and server;
- `system.auto_demo_armed = true` in the hashed TOML;
- explicit `--auto-demo` CLI flag;
- `CATALYST_AUTO_DEMO_CONFIRM=DEMO_ONLY`;
- local control token;
- healthy SQLite journal;
- successful restart reconciliation;
- clear persistent kill switch;
- fresh market data;
- valid symbol mapping/economics;
- strategy/risk gates passing.

A restart never silently restores the old armed state; the runner must pass the startup/arming checks again.

---

## 12. Entry and exit behavior in Auto-Demo

For an accepted setup the runtime:

1. persists the decision;
2. persists managed-position exit metadata;
3. reserves the durable idempotency key;
4. rechecks demo account/connectivity;
5. sends at most one entry request;
6. includes the mandatory server-side protective stop in the initial request.

CATALYST then manages only positions carrying its own MT5 magic number and deterministic `CAT-...` comment. Manual or unrelated MT5 positions are not touched.

A CATALYST-managed position is reduced/closed when the existing deterministic intraday exit engine requires it, including:

- missing protective stop -> emergency exit;
- protective-stop condition;
- complete pre-event-range reclaim;
- configured session cutoff.

Exit orders are reduce-risk operations and remain available even when new entries are disarmed or the kill-switch latch is active. Each exit attempt is sent at most once; an ambiguous result is not blindly retried.

The persistent managed-position file is normally:

```text
.runtime/managed-positions.json
```

Do not edit or delete it while a CATALYST-managed position is open. If the runtime finds a CATALYST-tagged position without valid persisted metadata, it chooses the conservative reduce-risk path rather than inventing an exit plan.

---

## 13. Emergency kill switch

From another PowerShell window:

```powershell
catalyst-kill-switch --path .runtime/kill-switch.json --reason "operator stop"
```

This immediately blocks **new** CATALYST entries at the guarded broker boundary. The auto-demo runtime can still perform reduce-risk exits on already-open CATALYST positions.

Do not manually delete the kill-switch file during an unresolved incident. Inspect MT5 positions/orders and journal state first. The normal control design clears the latch only after authenticated incident acknowledgement while execution is disarmed and the journal is healthy.

---

## 14. Risk configuration

The example settings currently include:

```toml
[risk]
risk_fraction = "0.05"
maximum_daily_loss_r = "3"
maximum_consecutive_losses = 3
maximum_active_risk_clusters = 1
monthly_fresh_capital_chf = "1000.00"
allow_averaging_down = false
allow_overnight = false
```

A 5% per-trade risk fraction is extremely aggressive. Demo testing can still lose the entire account. Tighten risk freely; do not raise the hard-approved limit without a deliberate code/policy revision.

---

## 15. Shutdown procedure

Normal shutdown:

1. Press `Ctrl+C`.
2. The runner disarms automatic demo execution.
3. It disconnects MT5.
4. It closes the SQLite journal and releases its single-instance lock.

Before closing the computer or MT5 while an auto-demo position exists, check that no CATALYST-managed position is being left beyond its intended intraday cutoff. If the runner stopped because of an ambiguous broker result, investigate/reconcile rather than resending manually.

For an incident, engage the kill switch first:

```powershell
catalyst-kill-switch --path .runtime/kill-switch.json --reason "incident shutdown"
```

---

## 16. Validation

Synthetic replay:

```powershell
$env:PYTHONPATH = "src"
python -m catalyst.replay_demo
```

Historical/demo observation validation:

```powershell
catalyst-validate observations.json validation-output --strategy-version <frozen-version>
```

Review:

```text
validation-output\validation_report.json
validation-output\validation_report.md
```

A `CONTINUE` result is a research/demo promotion gate only. It is not evidence that real-money trading will be profitable.

---

## 17. Minimal checklist before every Auto-Demo session

- [ ] repository is current `main`
- [ ] virtual environment is active
- [ ] MT5 is running
- [ ] correct **demo** account is logged in
- [ ] exact demo server matches configuration
- [ ] all primary and related symbols are mapped
- [ ] commission/slippage/conversion assumptions reviewed
- [ ] `catalyst-mt5-shadow-smoke` ends with `orders_sent=0`
- [ ] `.runtime/events.csv` contains current UTC events
- [ ] `.runtime/live_runtime.json` contains intended confirmation rules
- [ ] `catalyst-run --preflight-only` passes
- [ ] restart reconciliation has no unresolved intents
- [ ] kill switch is clear before new entries are armed
- [ ] Shadow Mode has been observed successfully
- [ ] only then start `catalyst-run --auto-demo`

## Related documentation

- `README.md`
- `docs/10_OPERATOR_RUNBOOK.md`
- `docs/05_DATA_CONTRACTS.md`
- `config/settings.example.toml`
- `config/live_runtime.example.json`
- `config/events.example.csv`

**Never use this MVP with a real account. Demo performance does not establish profitability or live execution quality.**
