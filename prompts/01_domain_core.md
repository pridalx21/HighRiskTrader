# Prompt 01: Harden the deterministic domain core

## Goal

Complete Phase 1 so every v1 strategy and risk decision can be produced from
immutable, validated inputs without MT5, network, database, or wall-clock calls.

## Context

Read `AGENTS.md`, `docs/02_ARCHITECTURE.md`, `docs/03_STRATEGY_SPEC.md`,
`docs/04_RISK_POLICY.md`, `docs/05_DATA_CONTRACTS.md`, and
`docs/06_TESTING_AND_ACCEPTANCE.md`. Inspect all current source and tests.

## Required work

- Add stable machine-readable rejection/state reason codes.
- Harden domain validation for timezone, bid/ask, range, stop direction, and
  invalid decimal values.
- Add explicit broker contract metadata: tick size/value, contract size,
  account currency, volume minimum/maximum/step.
- Implement volume-step rounding down and post-rounding risk recalculation.
- Load strategy/risk configuration from TOML into immutable validated objects.
- Compute a deterministic configuration hash stored on every decision.
- Expand state-machine, strategy, risk, sizing, and pipeline tests.
- Keep the public pipeline callable from replay and demo with the same types.

## Constraints

- Standard library only in the runtime core.
- `Decimal` for all money, prices, and quantities.
- No current-time, network, MT5, persistence, UI, or LLM dependency.
- No broad parameter optimization.
- Reject missing/unknown metadata; never use guessed defaults in execution.
- Do not weaken demo-only or one-cluster limits.

## Done when

- all baseline checks pass;
- success and every fail-closed path have tests;
- exact volume sizing is tested at min/max/step boundaries;
- core decisions serialize deterministically;
- public configuration is documented;
- `PROJECT_STATUS.md` and decision log are updated.

