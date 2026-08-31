# CATALYST — How to start on an MT5 demo account

This guide describes the supported Windows startup path for the CATALYST MVP.

> **Safety boundary:** CATALYST is demo-only. Never use a real-money MT5 account with this MVP. The adapter positively verifies MT5 demo mode and fails closed if account mode, login, server, connectivity, market data, journal state, or reconciliation cannot be verified.

## 1. What you need

- Windows 10/11
- Python 3.11+
- Git
- MetaTrader 5 installed
- A dedicated **MT5 demo account**
- The demo account already logged in successfully in the normal MT5 terminal
- The HighRiskTrader repository

Recommended: use a demo balance close to the intended test capital, e.g. CHF 1,000.

Do **not** store the MT5 password in Git. CATALYST's shadow smoke command relies on the locally saved MT5 terminal login/profile.

---

## 2. Clone the repository

Open PowerShell:

```powershell
git clone https://github.com/pridalx21/HighRiskTrader.git
cd HighRiskTrader
```

If the repository is already present:

```powershell
git pull origin main
```

---

## 3. Create a Python environment

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install development, MT5, and optional UI dependencies:

```powershell
python -m pip install -e ".[dev,mt5,ui]"
```

Check that the MT5 Python package imports:

```powershell
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
```

---

## 4. Verify the CATALYST installation first

Before connecting to MT5, run the repository verification:

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
4. Open `File -> Open an Account` / account properties as needed and note:
   - demo login number
   - exact server name
5. Confirm that the account is explicitly a demo account.
6. Keep the terminal installed at a known location, for example:

```text
C:\Program Files\MetaTrader 5\terminal64.exe
```

The exact path depends on the broker/installation.

### Find the broker symbol names

CATALYST uses logical names such as:

```text
US100
US500
XAUUSD
EURUSD
USDJPY
USDCHF
GER40
```

Your broker may use different names, for example `USTEC`, `NAS100`, `US500.cash`, `XAUUSD.a`, etc.

In MT5 open **Market Watch** and record the exact broker symbol for every logical symbol you want CATALYST to use.

Do not guess symbol names.

---

## 6. Configure MT5 variables in PowerShell

These variables exist only in the current PowerShell process and are therefore preferable to committing credentials/configuration.

Example:

```powershell
$env:CATALYST_MT5_TERMINAL_PATH = "C:\Program Files\MetaTrader 5\terminal64.exe"
$env:CATALYST_MT5_LOGIN = "12345678"
$env:CATALYST_MT5_SERVER = "YourBroker-Demo"
```

Configure logical-to-broker symbols. Replace the examples with the **exact** symbols from Market Watch:

```powershell
$env:CATALYST_MT5_SYMBOL_MAPPING_JSON = '{"US100":"USTEC","US500":"US500","XAUUSD":"XAUUSD","EURUSD":"EURUSD","USDJPY":"USDJPY","USDCHF":"USDCHF"}'
```

Every configured logical symbol also needs explicit execution economics:

```powershell
$env:CATALYST_MT5_ECONOMICS_JSON = '{"US100":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"US500":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"XAUUSD":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"EURUSD":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"USDJPY":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"},"USDCHF":{"commission_per_volume":"1.00","slippage_ticks":"2","profit_to_account_rate":"1"}}'
```

**The numbers above are placeholders, not broker facts.** Obtain the real commission assumptions from the broker. Use a pessimistic slippage allowance. `profit_to_account_rate` converts the instrument profit currency into the account currency; use the correct value for the account/instrument combination rather than assuming `1` when conversion is required.

CATALYST rejects a symbol if mapping or economics are missing.

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

The command checks:

- terminal connection
- configured login
- exact demo server
- explicit MT5 demo account mode
- logical-to-broker symbol mapping
- broker contract metadata
- latest bid/ask ticks
- open positions
- pending orders

It **does not send any order**.

If this command fails, stop here. Do not enable demo execution until the cause is understood.

Typical failures:

- wrong `terminal64.exe` path
- MT5 terminal not logged into the expected account
- server name does not match exactly
- account is not positively identified as demo
- broker symbol mapping is wrong
- market is closed / no recent tick available
- missing economics entry
- stale price data

---

## 8. Strategy/risk configuration

The executable configuration contract is:

```text
config/settings.example.toml
```

Important safe defaults:

```toml
[system]
demo_only = true
auto_demo_armed = false

[risk]
risk_fraction = "0.05"
maximum_daily_loss_r = "3"
maximum_consecutive_losses = 3
maximum_active_risk_clusters = 1
monthly_fresh_capital_chf = "1000.00"
allow_averaging_down = false
allow_overnight = false

[execution]
mode = "shadow"
require_initial_stop = true
blind_order_retry = false
maximum_submit_attempts = 1
```

Do not disable the demo-only, mandatory-stop, no-averaging-down, no-overnight, or no-blind-retry safeguards.

The current 5% risk fraction is intentionally very aggressive. Demo testing can still lose the entire account.

---

## 9. Event calendar

The initial MVP uses strict CSV event input. Example:

```text
config/events.example.csv
```

Schema:

```text
event_id,name,scheduled_at,currency,importance,status,eligible_symbols,source,actual,consensus,previous
```

Times must be explicit UTC timestamps, for example:

```text
2026-09-03T12:30:00+00:00
```

Logical symbols in `eligible_symbols` are separated with `|`:

```text
US100|US500|XAUUSD|EURUSD|USDJPY|USDCHF
```

Do not use the synthetic 2030 example events for real demo operation. Create a local event CSV with the actual scheduled releases you intend to observe.

---

## 10. Persistent runtime directory and kill switch

Use a non-tracked runtime directory:

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
```

Emergency stop:

```powershell
catalyst-kill-switch --path .runtime/kill-switch.json --reason "operator stop"
```

Once this latch exists, the guarded broker path must reject new submissions.

Do not manually delete the kill-switch file during an unresolved incident. First inspect broker orders/positions and journal state. The normal design clears the latch only through the authenticated incident-acknowledgement control while execution is disarmed and the journal is healthy.

---

## 11. Correct startup sequence for an automated demo session

The required composition order is:

1. Verify the persistent kill-switch state.
2. Load and validate the strict strategy/risk configuration.
3. Open `SQLiteJournal` and obtain its single-instance lock.
4. Build `MT5DemoBroker` with exact terminal/login/server/mapping/economics.
5. Wrap the broker in `GuardedDemoBroker` using the persistent kill-switch latch.
6. Connect and positively verify demo account mode, login, server, and connectivity.
7. Run restart reconciliation for every unresolved durable order intent.
8. Load the strict UTC event CSV.
9. Warm the required bid/ask and cross-asset evidence.
10. Build the dashboard/operator snapshot.
11. Start **disarmed**.
12. Arm automatic demo execution only after fresh state, healthy journal, successful reconciliation, clear kill switch, and explicit operator confirmation.

After every process restart, execution starts disarmed again.

---

## 12. Important current MVP limitation

At the current MVP release, the repository contains the complete deterministic core, journal, MT5 demo broker/order adapter, reconciliation, kill-switch/control plane, dashboard presentation model, replay/validation framework, and the real-terminal shadow smoke command.

However, the repository does **not yet expose the entire automated session composition above as one standalone command such as `catalyst-run`**. The currently packaged real-MT5 executable is:

```powershell
catalyst-mt5-shadow-smoke
```

Therefore:

- **Real MT5 demo connectivity/shadow observation:** ready to run now.
- **Core demo order submission and safety components:** implemented and tested.
- **One-command unattended auto-demo daemon:** not yet packaged as a public CLI.

Do not treat `catalyst-mt5-shadow-smoke` as an auto-trader; its success explicitly ends with `orders_sent=0`.

Before leaving CATALYST unattended on the demo account, add/verify the final runtime composition/runner that wires the already implemented components in the startup order listed above.

---

## 13. Validation before trusting demo results

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

A `CONTINUE` result is only a research/demo promotion gate. It is not permission or evidence for real-money trading.

---

## 14. Shutdown procedure

For a normal shutdown:

1. Disarm automatic demo execution.
2. Check open CATALYST-managed demo positions/orders.
3. Reconcile broker and journal state.
4. Apply the configured intraday close policy.
5. Disconnect MT5 cleanly.
6. Close the SQLite journal and release its lock.

For an incident or uncertain broker state, engage the kill switch first:

```powershell
catalyst-kill-switch --path .runtime/kill-switch.json --reason "incident shutdown"
```

Do not blindly resend an order after a timeout or unknown result. The system intentionally treats ambiguous submission outcomes as uncertain and requires reconciliation.

---

## 15. Minimal checklist before every demo session

- [ ] Repository is on current `main`
- [ ] Virtual environment is active
- [ ] MT5 is running
- [ ] Correct demo account is logged in
- [ ] Exact demo server matches configuration
- [ ] Symbol mapping checked against Market Watch
- [ ] Commission/slippage/conversion assumptions reviewed
- [ ] `catalyst-mt5-shadow-smoke` ends with `orders_sent=0`
- [ ] Event CSV contains current UTC events
- [ ] Journal is healthy and single-instance lock acquired
- [ ] Restart reconciliation has no unresolved intents
- [ ] Kill switch is clear
- [ ] Market data is fresh
- [ ] System starts disarmed
- [ ] Only then consider arming automatic **demo** execution

## Related documentation

- `README.md`
- `docs/10_OPERATOR_RUNBOOK.md`
- `docs/05_DATA_CONTRACTS.md`
- `config/settings.example.toml`
- `config/events.example.csv`

**Never use this MVP with a real account. Demo performance does not establish profitability or live execution quality.**
