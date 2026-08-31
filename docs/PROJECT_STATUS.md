# Project status

## Current phase

Phase 3: strict event data and durable append-only journal complete.

## Completed

- Product, scope, architecture, strategy, risk, data, testing, and operations
  contracts drafted.
- Repository-wide Codex instructions added.
- Dependency-light domain and decision skeleton added.
- Demo-only risk invariant implemented.
- In-memory fake broker and end-to-end sample added.
- Baseline unit and integration tests added.
- Ordered phase prompts prepared.
- Repository initialized with Git; the verified Phase 0-1 state is committed on
  local branch `main`.
- Standard-library baseline verified on Windows with Python 3.14.4.
- Same-setup idempotency no longer changes with evaluation time; a second
  evaluation is rejected by the fake broker as a duplicate.
- Risk configuration can tighten but cannot raise the approved 5% initial-risk
  default without a future policy and code revision.
- Phase 1 implementation plan added in `docs/PHASE_1_PLAN.md`.
- Stable outcome-specific gate, state, risk, and pipeline reason codes added.
- Domain inputs now require UTC and reject float/non-finite monetary values.
- Explicit broker contract metadata and exact volume-step rounding added; plans
  include recalculated maximum loss after commission and slippage allowance.
- Daily lock now counts realized losses plus open worst-case risk.
- Strict standard-library TOML loading, safe default disarm, one coherent
  strategy/state/risk configuration, and deterministic SHA-256 hashing added.
- Accepted and rejected decisions serialize deterministically and contain the
  same configuration hash.
- Fake broker contract metadata port and fail-closed MT5 placeholder completed.
- Strict UTC/Decimal JSON contracts for raw bid/ask ticks and bars completed.
- Deterministic features now reconstruct highest ask, lowest bid, median spread,
  true-range evidence, first breakout/retest/hold, range reclaim, whipsaw, and
  timestamped cross-asset votes.
- A stable replay clock orders events, completed bars, and ticks independently
  of fixture input order.
- Replay execution records executable-side fills, latency, spread, adverse
  slippage, commission, rejection, missed fills, and step-rounded partial fills.
- The shared pure intraday exit engine implements emergency, protective stop,
  complete-range reclaim, and UTC cutoff precedence and forbids stop widening.
- Seven synthetic scenarios use the unchanged public `DecisionPipeline` and
  export one byte-stable canonical JSON report with raw inputs, decisions,
  execution, exits, costs, P&L/R, and SHA-256 hashes.
- ADR-008 through ADR-011 record the Phase 2 storage, feature, execution, and
  exit decisions.
- Phase 3 implementation plan added in `docs/PHASE_3_PLAN.md`.
- Exact manual CSV schema now requires UTC, explicit importance/status,
  pipe-delimited logical symbols, finite optional decimal strings, and source
  identity while preserving all ordered source fields.
- SQLite WAL journal now applies checksummed migrations, foreign keys, full
  synchronization, immutable-table triggers, a global SHA-256 entry chain, and
  an operating-system single-instance lock.
- Events and complete decisions must be durable before a unique order intent
  can be reserved; repeated identical imports and entries are idempotent.
- Durable demo execution submits a reserved key at most once. Timeouts and
  exceptions become explicit uncertain states without automatic retry.
- The durable executor positively rechecks demo mode and broker connectivity
  immediately before submission; real, unknown, disconnected, or unreadable
  account state is terminal and never reaches the order call.
- Broker-neutral restart reconciliation resolves positively found orders and
  leaves not-found, unknown, and adapter-error outcomes disarmed.
- Canonical audit export reconstructs an event from ordered source fields
  through decision, order lifecycle, fills, and outcome with a bundle hash.
- Migration mismatch, corruption, secret-bearing fields, second instances,
  invalid lifecycle transitions, and crash/restart paths have failure tests.
- ADR-012 through ADR-014 record the CSV, SQLite, and reserve-before-submit
  decisions.
- Existing CI formatting/type issues were repaired; Ruff, Ruff format, mypy,
  pytest, and the 85% coverage gate now pass.

## Not implemented

- Structured/provider calendar adapter beyond the manual CSV boundary.
- MT5 market-data and order adapter.
- Dashboard and kill switch.
- Strategy validation harness.

## Resolved discrepancies

Two starter defects were repaired with regression coverage:

- The setup identifier included evaluation time, so the same setup evaluated a
  second later bypassed in-memory duplicate rejection. It now follows the
  documented stable v1 setup-sequence formula.
- `RiskPolicy` accepted a config-only increase from 5% to 10%. The highest
  priority policy permits only tightening without explicit approval and a code
  revision, so the current implementation now rejects values above 5%.

Phase 1 also resolved the previously planned UTC, reason-code, broker-metadata,
rounding, configuration, and deterministic-serialization gaps.

The remaining differences are planned work, not enabled behavior: Phases 4-6
cover the MT5 demo adapter, kill switch/dashboard, and validation harness.

No executable live-account path, network call, wall-clock call, float-based
money arithmetic, credential, or order path without an initial protective stop
was found. The MT5 placeholder remains fail-closed. Repository-local Git author
identity is configured as explicitly provided by the operator.

## Known assumptions

- Python 3.11+.
- MT5 demo integration will run on Windows.
- Initial event data can be supplied by strict manual CSV.
- Logical broker symbols require explicit mapping.
- Core tests must remain runnable without optional dependencies.

## Open decisions

- Exact MT5 demo broker and its logical-to-broker symbol mapping.
- Calendar provider after CSV replay is stable.
- Session cutoff per logical instrument.
- Historical data source and licensing for validation.

None of these permits weakening the demo-only or fail-closed rules.

## Next task

Start `prompts/04_mt5_demo.md`: implement the Windows MT5 market-data and order
adapter in shadow mode first, with explicit demo-account verification and the
Phase 3 reconciliation boundary. Broker and logical-symbol mapping must be
selected explicitly; no live path may be added.

## Last verification

```text
Date: 2026-08-28
Environment: Linux 6.18.35 x86_64
Python: 3.12.13
Commands:
  bash scripts/verify.sh
  ruff check .
  ruff format --check .
  mypy src
  pytest --cov=src/catalyst --cov-report=term-missing --cov-fail-under=85
  PYTHONPATH=src python -m compileall -q src tests scripts
  Repeated canonical replay byte/hash comparison
Result:
  Complete suite: 183 tests passed; total branch coverage 85.88%.
  Ruff lint/format and strict mypy checks passed.
  Demo: state=ready with an accepted fake-broker bracket and mandatory stop.
  Replay: all 7 exact expected outcomes matched.
  Configuration hash:
    5419b8328d95605edb14ee2e70421a03a8a0b7aafd454b8dbe80edbd962010f5
  Canonical report hash:
    291994ff87ee609a2793e2050ac2b5001cfae675b59debecfdbdf562a5006d6e
  Canonical report length: 35,343 UTF-8 bytes.
```
