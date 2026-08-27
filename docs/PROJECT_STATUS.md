# Project status

## Current phase

Phase 2: deterministic event replay and market features complete.

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

## Not implemented

- CSV/provider event adapter.
- Persistent journal and restart reconciliation.
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

The remaining differences are planned work, not enabled behavior:

- Phase 3: persistent idempotency, journal, CSV calendar, and restart
  reconciliation.
- Phases 4-6: MT5 demo adapter, kill switch/dashboard, and validation harness.

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

Start `prompts/03_event_data_and_journal.md`: implement strict event ingestion,
the persistent append-only journal, durable idempotency, and restart
reconciliation without adding MT5 or a live path.

## Last verification

```text
Date: 2026-08-27
Environment: Microsoft Windows NT 10.0.26200.0 AMD64; PowerShell 5.1.26100.9168
Python: 3.14.4
Commands:
  powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
  $env:PYTHONPATH = "src"; python -m catalyst.replay_demo
  $env:PYTHONPATH = "src"; python -m compileall -q src tests scripts
  Repeated canonical replay byte/hash comparison
  Repository scans for live/order/network/clock/float bypasses, secrets,
  generated artifacts, trailing whitespace, and Python lines over 100 columns
Result:
  Complete suite: 131 tests passed.
  Demo: state=ready with an accepted fake-broker bracket and mandatory stop.
  Replay: all 7 exact expected outcomes matched.
  Configuration hash:
    5419b8328d95605edb14ee2e70421a03a8a0b7aafd454b8dbe80edbd962010f5
  Canonical report hash:
    291994ff87ee609a2793e2050ac2b5001cfae675b59debecfdbdf562a5006d6e
  Canonical report length: 35,343 UTF-8 bytes.
Optional tools:
  ruff, mypy, and pytest were not installed; no optional check was claimed.
```
