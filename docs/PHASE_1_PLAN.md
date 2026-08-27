# Phase 1 implementation plan

## Outcome

Complete the Phase 1 exit criterion from `docs/09_DEVELOPMENT_PLAN.md`: every
strategy and risk decision is produced from immutable, validated inputs, with
stable reason codes, exact broker-aware sizing, validated TOML configuration,
and a deterministic configuration hash. The runtime core remains standard
library only and shared by replay and demo execution.

## Normative context

Apply documents in this order:

1. `docs/04_RISK_POLICY.md`
2. `docs/03_STRATEGY_SPEC.md`
3. `docs/02_ARCHITECTURE.md`
4. `docs/06_TESTING_AND_ACCEPTANCE.md`
5. `docs/01_MVP_SCOPE.md`
6. `docs/PROJECT_STATUS.md`

Relevant implementation starts in `src/catalyst/domain`, `strategy`, `risk`,
and `engine`; public examples start in `config/settings.example.toml` and
`src/catalyst/demo.py`.

## Constraints and assumptions

- Keep the approved default and maximum configurable initial risk at 5%; the
  documented 10% software ceiling is not permission for a config-only increase.
- Require UTC, not merely a timezone-aware offset, at domain boundaries.
- Require explicit broker metadata and currency conversion inputs. Remove the
  executable sizing assumption that `value_per_price_unit` equals one.
- Use positive `Decimal` values and round positive volume down with the broker
  step. Reject zero, below-minimum, above-maximum, missing, non-finite, or
  post-cost over-risk results.
- Preserve one setup sequence per event/instrument/direction in v1. Persistent
  idempotency and cross-process reconciliation remain Phase 3 work.
- Keep strategy defaults unchanged and use no MT5, network, database, UI, LLM,
  current-time, or random dependency.

## Implementation slices

### 1. Domain validation and stable reason codes

- Files: `src/catalyst/domain/enums.py`, `src/catalyst/domain/models.py`,
  `src/catalyst/strategy/event_reaction_retest.py`,
  `src/catalyst/engine/state_machine.py`, `src/catalyst/engine/pipeline.py`, and
  their exports.
- Behavior: introduce serialized rejection/state codes; require each rejected
  gate, risk result, and pipeline result to expose a machine code and readable
  reason; require UTC timestamps; validate all decimal, bid/ask, range, count,
  and stop invariants before evaluation.
- Failure paths: naive or non-UTC timestamps, NaN/infinity, invalid price
  ordering, invalid range, impossible confirmation counts, wrong-side or equal
  stop, and a ready result without a direction.
- Tests: expand `tests/unit/test_domain.py`, `test_strategy.py`,
  `test_state_machine.py`, and `test_pipeline.py` with boundary and serialized
  code assertions for every gate and state.

### 2. Broker contract metadata and exact sizing

- Files: `src/catalyst/domain/models.py`, `src/catalyst/risk/manager.py`,
  `src/catalyst/engine/pipeline.py`, `src/catalyst/ports/broker.py`,
  `tests/fixtures.py`, `tests/unit/test_risk_manager.py`, and
  `tests/unit/test_pipeline.py`.
- Behavior: add immutable metadata for tick size/value, contract size, profit
  and account currencies, explicit conversion, volume minimum/maximum/step, and
  pessimistic cost/slippage allowance. Calculate raw volume, round down to an
  exact step, and recalculate worst-case loss after rounding before producing a
  plan.
- Failure paths: missing/unknown metadata or conversion, incompatible step and
  limits, raw volume outside broker bounds, rounded zero/below minimum, and
  recalculated loss above permitted risk. Do not cap or round up silently.
- Tests: exact-step, fractional-step, min/max boundary, just-over-max,
  below-minimum, conversion, non-finite metadata, wrong stop side, and
  post-cost rejection cases.

### 3. Validated TOML configuration and one coherent runtime config

- Files: add `src/catalyst/config.py`; update
  `src/catalyst/strategy/event_reaction_retest.py`,
  `src/catalyst/engine/state_machine.py`, `src/catalyst/risk/policy.py`,
  `src/catalyst/engine/pipeline.py`, `config/settings.example.toml`, and
  `src/catalyst/demo.py`.
- Behavior: parse with `tomllib`, convert decimal strings explicitly, reject
  unknown/missing keys, construct immutable strategy/state/risk settings from
  one validated object, and enforce `demo_only = true`, UTC, and tightening-only
  risk limits. Eliminate independently configurable shock/deadline values that
  can diverge between strategy and state machine.
- Failure paths: malformed TOML, unknown keys, wrong scalar types, float money,
  non-UTC timezone, `demo_only = false`, strategy/state timing disagreement,
  and any risk limit above its approved value.
- Tests: add `tests/unit/test_config.py` using temporary files for the checked-in
  example, minimal valid config, each invalid type/key, and each attempted
  safety relaxation.

### 4. Deterministic configuration hash and decision serialization

- Files: add `src/catalyst/domain/serialization.py`; update
  `src/catalyst/domain/models.py`, `src/catalyst/engine/pipeline.py`,
  `tests/unit/test_pipeline.py`, and add deterministic serialization fixtures.
- Behavior: canonicalize enums, UTC datetimes, timedeltas, and `Decimal` values
  into sorted, whitespace-stable JSON; hash the complete decision-affecting
  configuration with SHA-256; store the hash on every pipeline decision and
  trade plan.
- Failure paths: unsupported field types, incomplete configuration, locale- or
  insertion-order-dependent output, and hash omission on rejection decisions.
- Tests: byte-for-byte repeatability, equivalent key-order equality, one-field
  hash change, accepted/rejected decision coverage, and replay/demo use of the
  same public `DecisionPipeline.evaluate` entry point.

### 5. End-to-end hardening and documentation

- Files: `tests/integration/test_demo_pipeline.py`, `src/catalyst/demo.py`,
  `README.md`, `docs/08_DECISION_LOG.md`, and `docs/PROJECT_STATUS.md`.
- Behavior: update the broker-free demo to supply explicit metadata/config;
  retain initial protective stop and demo-only enforcement; document public
  configuration and canonical hashing/sizing decisions.
- Failure paths: real/unknown/disconnected account, stale data, spread spike,
  missing or invalid stop/metadata, duplicate setup, active cluster, loss
  streak, and daily lock.
- Tests: extend the integration suite so both a valid synthetic bracket and
  each safety rejection pass through the same pipeline without network, clock,
  randomness, or broker packages.

## Verification

Run after each slice and at completion:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m catalyst.demo
```

If installed, also run `ruff check .`, `ruff format --check .`, `mypy src`, and
`pytest --cov=catalyst --cov-report=term-missing`. Review the final diff for
real-account paths, missing initial stops, float arithmetic, fail-open missing
data, divergent replay/demo logic, nondeterminism, secret exposure, and
undocumented parameter changes.

## Explicit non-goals

- Historical feature building, replay clocks, exits, and cost simulation
  beyond the sizing allowance (Phase 2).
- Persistent journal, restart reconciliation, and CSV/provider adapters
  (Phase 3).
- MT5 or any broker/network integration (Phase 4).
- Streamlit/dashboard, kill-switch implementation, deployment, OpenClaw, n8n,
  machine learning, parameter search, live trading, or profitability claims.

## Completion record

- Completed: 2026-08-27.
- Standard-library verification: 98 tests passed; deterministic demo completed
  with `state=ready`, `broker_receipt=ACCEPTED`, and maximum loss below 1R.
- Optional checks: `ruff`, `mypy`, and `pytest` were unavailable and were not
  claimed.
- Safety review: no executable live-account path, missing-stop order path,
  float money arithmetic, network/current-time dependency, or replay/demo rule
  fork found. The MT5 placeholder remains fail-closed.
- Remaining limitations are the explicit Phase 2-6 non-goals above.
