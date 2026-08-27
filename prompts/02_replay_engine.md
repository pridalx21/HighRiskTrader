# Prompt 02: Build event replay and market features

## Goal

Build a deterministic historical event-replay vertical slice that derives the
v1 setup features from bid/ask-aware fixtures and sends them through the same
pipeline used by demo execution.

## Context

Read `AGENTS.md`, strategy, risk, architecture, data, and testing documents.
Phase 1 must be complete before starting.

## Required work

- Define raw tick/bar fixture contracts with UTC timestamps and bid/ask.
- Implement pre-event high/low and robust spread baseline.
- Implement deterministic breakout, first-retest, range-reclaim, and
  cross-asset vote features.
- Implement replay clock and stable ordering for equal timestamps.
- Implement spread, commission, latency, adverse slippage, missed-fill, rejected
  order, and partial-fill models.
- Implement the documented intraday exit engine in the same core used later by
  demo execution.
- Create synthetic fixtures for long pass, short pass, whipsaw, stale data,
  spread spike, missing confirmation, and late setup.
- Export a complete, reproducible JSON replay report.

## Constraints

- Do not use midpoint fills when an executable bid/ask side is required.
- No vectorized shortcut may reimplement different strategy logic.
- Fixed seeds for any stochastic stress model.
- No external data provider yet.
- No parameter search for best return.

## Done when

- replay is deterministic across repeated runs;
- synthetic expected outcomes are asserted exactly;
- all costs and skipped fills are visible in the report;
- replay decisions use the public core pipeline;
- failure fixtures demonstrate fail-closed behavior;
- docs, ADRs, and project status are updated.

