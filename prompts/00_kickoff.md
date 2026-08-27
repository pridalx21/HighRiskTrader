# Prompt 00: Baseline and Phase 1 plan

## Goal

Verify that the extracted CATALYST starter is internally consistent and create
a concrete Phase 1 implementation plan. Do not add product features yet.

## Context

Read:

- `AGENTS.md`
- `README.md`
- every file in `docs/`
- current source and tests

The repository is a demo-only event-conditioned intraday trading MVP. The
highest-priority specification is `docs/04_RISK_POLICY.md`.

## Tasks

1. List the active project instructions and normative-document precedence.
2. Inspect the repository tree and current implementation.
3. Run the baseline commands from `AGENTS.md`.
4. Compare docs, models, code, and tests for contradictions or missing safety
   invariants.
5. Fix only clear starter defects required for a clean baseline.
6. Produce a Phase 1 plan mapped to `docs/09_DEVELOPMENT_PLAN.md`.
7. Update `docs/PROJECT_STATUS.md` with environment, commands, results,
   discrepancies, and the next task.

## Constraints

- Do not install or integrate MT5, Streamlit, n8n, OpenClaw, a database, or a
  calendar provider.
- Do not change strategy or risk defaults.
- Do not add a live-trading path.
- Do not claim profitability.
- Preserve standard-library baseline verification.

## Done when

- baseline tests and demo pass;
- any repaired starter defect has a regression test;
- repository contracts do not contradict implementation;
- `PROJECT_STATUS.md` contains exact verification evidence;
- the Phase 1 plan names files, tests, failure paths, and explicit non-goals.

