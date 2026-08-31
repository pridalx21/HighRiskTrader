# CATALYST MVP

CATALYST is a demo-only, event-conditioned intraday trading system starter. It
uses scheduled market events to decide *when* to watch, price acceptance to
decide *whether* a move is real, cross-asset confirmation to reduce false
breakouts, and deterministic risk rules to decide whether an order may exist.

This archive is not a finished trading bot and contains no claim of
profitability. It is a build contract, a tested domain skeleton, and an ordered
set of prompts for implementing the MVP safely with Codex.

## The product in one sentence

> Event says when; price says direction; related markets confirm; risk decides.

## Start here

1. Extract the archive into a new Git repository.
2. Open the extracted repository root in Codex.
3. Ask Codex: `Summarize the active AGENTS.md instructions and run the baseline verification.`
4. Review [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).
5. Use [prompts/00_kickoff.md](prompts/00_kickoff.md) as the first implementation task.
6. Complete prompts in numerical order. Do not jump directly to MT5 execution.

## Baseline verification

No broker, API key, database, or third-party package is required for the
starter tests.

### Windows PowerShell

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m catalyst.demo
python -m catalyst.replay_demo
```

Or run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

### Linux, macOS, or WSL

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m catalyst.demo
PYTHONPATH=src python -m catalyst.replay_demo
```

Or run:

```bash
bash scripts/verify.sh
```

## Recommended development environment

- Python 3.11 or newer
- Windows for the later MetaTrader 5 adapter
- Git from the first implementation task onward
- A dedicated MT5 demo account with a realistic CHF 1,000 balance

Optional development tools can be installed with:

```bash
python -m pip install -e ".[dev]"
```

The MT5 package and dashboard dependencies are deliberately optional:

```bash
python -m pip install -e ".[dev,mt5,ui]"
```

## Repository map

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Durable project instructions automatically read by Codex |
| `PLANS.md` | Execution-plan template for multi-component phases |
| `docs/` | Product, architecture, strategy, risk, testing, and operations contracts |
| `prompts/` | Ordered Codex implementation prompts |
| `src/catalyst/` | Dependency-light functional core and adapter boundaries |
| `tests/` | Executable examples and safety invariants |
| `config/` | Example settings, instrument mapping, and synthetic events |
| `scripts/` | Cross-platform baseline verification |

## MVP boundaries

The MVP may:

- ingest a structured calendar or the included CSV fixture;
- consume MT5 demo prices;
- evaluate the Event Reaction Retest strategy;
- calculate a risk-bounded trade plan;
- submit bracket orders only to an account verified as demo;
- record every decision and explain every rejected setup;
- replay historical events through the same decision pipeline;
- present a simple read-only dashboard and a kill switch.

The MVP may not:

- trade a real account;
- average down, martingale, grid, or remove a protective stop;
- let an LLM create or modify numeric order parameters;
- scrape arbitrary web pages in the execution path;
- trade the first release spike;
- silently continue with stale data or a disconnected broker;
- optimize for win rate or raw return without costs and out-of-sample evidence.

## Architecture principle

The strategy and risk logic form a deterministic functional core. Replay,
paper, and MT5 demo modes are adapters around that same core. If a rule cannot
be reproduced in replay, explained in the journal, and tested without a broker,
it does not belong in the order path.

## Current state

The starter includes:

- validated domain models;
- the first state machine;
- the four strategy gates;
- a demo-only risk manager;
- a trade-plan pipeline;
- an in-memory demo broker;
- unit and integration tests;
- a deterministic demonstration command;
- the full implementation roadmap.

The current implementation also includes a strict UTC/Decimal JSON fixture
boundary, bid/ask feature reconstruction, stable replay clock, execution and
intraday exit models, seven synthetic scenarios, and a canonical JSON report.
It now also includes strict manual-CSV event ingestion, an append-only SQLite
WAL journal, durable order-intent idempotency, single-instance locking,
broker-neutral restart reconciliation, and canonical event audit bundles. The
MT5 order adapter, dashboard, and validation harness remain for the ordered
Codex phases.

## Phase 3 event data and durable journal

`catalyst.adapters.csv_event_feed.CsvEventFeed` parses the exact checked-in CSV
schema. It requires explicit UTC time, status, eligible logical symbols, and
source identity; preserves every ordered source field; and rejects duplicate
IDs, unknown enum values, malformed optional decimals, and implicit symbol
inference.

`catalyst.adapters.sqlite_journal.SQLiteJournal` uses checksummed migrations,
WAL, full synchronization, foreign keys, immutable-table triggers, a global
SHA-256 entry chain, and an operating-system file lock. Events and complete
decisions must be durable before an order key can be reserved. The durable demo
executor submits each key at most once. A timeout, crash, unknown broker state,
or failed reconciliation never causes automatic resubmission or automatic
arming. It also positively rechecks demo mode and connectivity immediately
before the order call. `export_event_audit_bundle` returns one canonical,
hashed record from source row through decision and outcome.

## Phase 2 deterministic replay

Run `python -m catalyst.replay_demo` with `PYTHONPATH=src` to replay the seven
checked-in cases under `tests/data/replay`. The command fails when any exact
expected outcome differs and otherwise prints one complete canonical report.
Every report contains the raw fixture, derived evidence, public-pipeline
decision, executable-side fill or explicit absence of execution, exit, costs,
configuration hash, fixture hashes, and report hash. It uses no broker,
network, current clock, random source, or third-party package.

## Phase 1 configuration and decision contract

`config/settings.example.toml` is now an executable, strict configuration
contract. `catalyst.config.load_runtime_config` rejects missing or unknown keys,
non-string decimal values, non-UTC operation, disabled demo-only protection,
risk above the approved 5% default, averaging down, overnight exposure, a
missing initial stop, blind retries, or any Phase 1 execution mode other than
`shadow`. Automatic demo execution is disarmed by default.

`DecisionPipeline.evaluate` requires an explicit immutable `BrokerContract`
containing tick size/value, contract size, currencies and conversion, volume
limits/step, commission, and slippage allowance. No executable
`value_per_price_unit = 1` fallback remains. Accepted and rejected decisions
carry stable reason codes and the same deterministic SHA-256 configuration
hash. `catalyst.domain.serialization.canonical_json` produces stable JSON for
replay comparison and journal persistence.

## Important warning

High leverage can lose the entire account. Stops can slip or gap. A demo result
does not prove live profitability or live execution quality. Before any future
live use, the user must separately verify broker terms, negative-balance rules,
instrument specifications, taxes, and legal suitability.
