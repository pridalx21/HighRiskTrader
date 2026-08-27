# Phase 2 execution plan

## Outcome

A deterministic, broker-free replay consumes bid/ask-aware UTC JSON fixtures,
derives the v1 pre-event range, spread, breakout/retest and related-market
evidence, evaluates the unchanged public `DecisionPipeline`, models execution
and approved exits on executable prices, and exports byte-stable JSON reports.

## Context

- Normative precedence: `docs/04_RISK_POLICY.md`, `docs/03_STRATEGY_SPEC.md`,
  `docs/02_ARCHITECTURE.md`, `docs/06_TESTING_AND_ACCEPTANCE.md`,
  `docs/01_MVP_SCOPE.md`, then `docs/PROJECT_STATUS.md`.
- Additional contract: `docs/05_DATA_CONTRACTS.md` and
  `prompts/02_replay_engine.md`.
- Existing components: immutable domain models, strict runtime configuration,
  `DecisionPipeline`, exact broker sizing, canonical JSON, and fake broker.
- Inputs: checked-in synthetic JSON only; no provider, MT5, network, current
  time, randomness, or external runtime package.

## Constraints and non-goals

- Replay and later demo execution share the same feature builder, pipeline,
  execution model interfaces, and exit engine. No vectorized parallel rules.
- Use executable ask for long entry, bid for short entry, bid for long exit,
  and ask for short exit. Midpoint is feature evidence only, never a fill.
- Preserve demo-only, initial-stop, 5% approved risk, one-cluster, Decimal,
  stale-data, and no-overnight invariants.
- JSON is the Phase 2 fixture and report boundary so the standard-library
  baseline remains install-free. Parquet is deferred until a real historical
  storage adapter is selected and its production dependency is approved.
- No real data, provider selection, database/journal, MT5, UI, optimization,
  stochastic fill claims, performance claims, or live execution.

## Assumptions and open questions

- A breakout is the first post-shock midpoint strictly outside the pre-event
  range. The first retest approaches the broken boundary from outside by no
  more than one broker tick; the next same-direction outside tick confirms the
  hold. A midpoint inside the complete range after breakout invalidates it.
- The initial protective stop is the opposite pre-event range boundary. This
  is conservative, deterministic, and uses already documented range evidence;
  no optimized stop distance is introduced.
- ATR evidence is the arithmetic mean of true ranges from ordered pre-event
  bid/ask bars. It is reporting/exit context only and never chooses direction.
- Related-market polarity and minimum move are explicit fixture/config inputs.
  Every observed vote stores its source tick timestamp; missing markets do not
  vote.
- Partial `+2R` realization and trailing are disabled because the strategy
  contract requires replay validation first. The initial exit engine supports
  hard stop, full-range reclaim, emergency exit, and explicit UTC session
  cutoff. A later approved strategy revision may enable partial/trailing rules.

## Implementation slices

### 1. Raw fixture and replay-domain contracts

- Files: add `src/catalyst/replay/models.py`,
  `src/catalyst/replay/fixture.py`, package exports, and
  `tests/unit/test_replay_models.py`.
- Behavior: immutable raw tick/bar, related-market rule/vote, feature evidence,
  execution scenario, exit, replay result, and report types; strict JSON parser
  for UTC ISO timestamps and decimal strings; unique scenario IDs and stable
  source sequence numbers.
- Failure paths: floats, naive/non-UTC/duplicate or decreasing sequences,
  inverted bid/ask, invalid bars, missing fields, unknown enum values, absent
  costs, invalid partial-fill fractions, or cutoff before event.
- Tests: exact valid parsing plus each validation failure without network.

### 2. Deterministic market feature builder

- Files: add `src/catalyst/replay/features.py` and
  `tests/unit/test_feature_builder.py`.
- Behavior: select the exact pre-event window; compute highest ask, lowest bid,
  median spread, ATR evidence, first breakout, first retest and hold, range
  reclaim/whipsaw invalidation, related votes with timestamps, and a complete
  `MarketSnapshot` consumed unchanged by the public pipeline.
- Failure paths: insufficient pre-event ticks/bars, missing primary symbol,
  crossed quotes, no breakout/retest, both-side break, full reclaim, stale
  evaluation tick, spread spike, missing votes, or late setup.
- Tests: exact feature values and reason evidence for long, short, whipsaw,
  stale, spread, missing-confirmation, and late fixtures.

### 3. Replay clock and execution model

- Files: add `src/catalyst/replay/clock.py`,
  `src/catalyst/replay/execution.py`, and focused unit tests.
- Behavior: merge ticks/bars/events with a documented timestamp/type/symbol/
  source-sequence ordering; delay entry by explicit latency; fill on executable
  bid/ask; record spread, commission, adverse slippage and requested/filled
  quantity; model deterministic rejection, missed fill, and step-rounded
  partial fill.
- Failure paths: no quote after latency, price beyond maximum adverse slippage,
  unknown rejection, partial fill below broker minimum, off-step volume, or
  inconsistent symbols.
- Tests: equal-timestamp byte-stable order, long/short sides, zero/non-zero
  latency, rejection, missed fill, and partial-fill boundaries.

### 4. Shared intraday exit engine

- Files: add `src/catalyst/engine/exit_engine.py`, extend stable reason codes,
  and add `tests/unit/test_exit_engine.py`.
- Behavior: pure engine accepts position, current tick, explicit cutoff and
  emergency state; precedence is emergency, protective stop, complete range
  reclaim, then cutoff; exits use executable bid/ask and never widen/remove the
  initial stop.
- Failure paths: stale/future quote, wrong symbol, invalid position/stop/range,
  no executable cutoff quote, and any attempted farther stop.
- Tests: long/short stop, reclaim, cutoff, emergency, precedence, side pricing,
  stale quote, and no-exit state.

### 5. End-to-end replay and canonical report

- Files: add `src/catalyst/replay/runner.py`,
  `src/catalyst/replay/report.py`, `src/catalyst/replay_demo.py`, synthetic JSON
  fixtures under `tests/data/replay/`, replay unit/integration tests, README,
  data/strategy/testing docs, ADRs, and `docs/PROJECT_STATUS.md`.
- Behavior: run each scenario through one feature builder and the public core
  pipeline; apply execution and exit models; calculate Decimal net P&L/R after
  costs; include inputs, ordered evidence, decisions, fills/skips/rejections,
  exits, costs, configuration hash, fixture hash, and report hash in canonical
  JSON.
- Failure paths: every required rejection fixture produces no order/fill;
  accepted decisions with rejected/missed execution remain explicit; any open
  position without an intraday exit makes the replay fail closed.
- Tests: exact long/short outcomes, all five failure scenarios, repeated-run
  byte equality, replay/demo pipeline-field equality, and JSON round-trip.

## Verification

- Baseline: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`.
- Replay: `$env:PYTHONPATH = "src"; python -m catalyst.replay_demo` twice and
  compare complete output bytes/hashes.
- Focused: standard-library `unittest` suites for fixtures, features, clock,
  execution, exits, reports, and integration.
- Optional if installed: Ruff, Mypy, and Pytest coverage.
- Static review: live-account path, missing stop, stale/ambiguous inputs,
  idempotency, float arithmetic, replay/demo divergence, secrets/generated
  artifacts, and unsupported profitability claims.

## Documentation and decisions

- Add ADRs for JSON fixture boundary, deterministic feature definitions,
  executable-side execution model, and conservative exit scope.
- Update strategy/data/testing contracts with exact Phase 2 definitions without
  changing risk limits or claiming edge.
- Update `PROJECT_STATUS.md` with commands, hashes, scenario outcomes,
  limitations, and `prompts/03_event_data_and_journal.md` as the next task.

## Completion record

Completed on 2026-08-27.

- Standard-library baseline: 131 tests passed; deterministic demo accepted one
  synthetic bracket with its initial stop.
- Seven replay scenarios matched their exact expected decision, direction,
  execution, and exit outcomes.
- Two complete CLI runs were byte-identical.
- Configuration hash:
  `5419b8328d95605edb14ee2e70421a03a8a0b7aafd454b8dbe80edbd962010f5`.
- Canonical report hash:
  `291994ff87ee609a2793e2050ac2b5001cfae675b59debecfdbdf562a5006d6e`.
- Compilation, whitespace, line-length, and fail-closed safety scans passed.
- Ruff, Mypy, and Pytest were unavailable, so no optional check is claimed.
