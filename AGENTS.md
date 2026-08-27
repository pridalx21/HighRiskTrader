# CATALYST repository instructions

## Mission

Build a transparent, deterministic, demo-only MVP for an event-conditioned
intraday trading system. The MVP optimizes for correctness, reproducibility,
explainability, and testability before speed or feature count.

## Instruction hierarchy

Before changing code, read the documents relevant to the task. These files are
normative in this order:

1. `docs/04_RISK_POLICY.md`
2. `docs/03_STRATEGY_SPEC.md`
3. `docs/02_ARCHITECTURE.md`
4. `docs/06_TESTING_AND_ACCEPTANCE.md`
5. `docs/01_MVP_SCOPE.md`
6. `docs/PROJECT_STATUS.md`

If two documents conflict, stop and document the conflict. Do not silently
choose the less restrictive trading behavior.

## Non-negotiable safety boundaries

- The project is `DEMO_ONLY` throughout the MVP.
- Reject any account that is not positively identified as a demo account.
- Never add a live-order bypass, hidden override, or `force=true` escape hatch.
- Every order must include a broker-side protective stop in the initial request.
- LLMs, OpenClaw, n8n, news prose, and dashboard text are outside the numeric
  decision and execution path.
- Never implement martingale, grid trading, averaging down, uncapped loss,
  short naked options, or automatic mid-month account refills.
- Never log passwords, account credentials, API keys, tokens, or complete broker
  responses containing secrets.
- Do not loosen `docs/04_RISK_POLICY.md` without explicit user approval and a
  recorded architecture decision.
- If data is stale, event timing is ambiguous, the broker disconnects, the
  spread gate fails, or risk cannot be calculated exactly, reject the trade.

## Engineering rules

- Use Python 3.11+ and type hints on public functions.
- Use timezone-aware UTC datetimes internally. Convert only at presentation
  boundaries.
- Use `Decimal` for money, price, risk, and position-size calculations.
- Keep the domain core independent of MT5, Streamlit, databases, networks, and
  environment variables.
- Express external systems as ports/protocols and implement them in adapters.
- Replay and demo execution must call the same strategy and risk pipeline.
- Prefer explicit state machines and named results over booleans with hidden
  meaning.
- Every rejection needs a machine-readable code and a human-readable reason.
- Keep configuration explicit. Do not hide strategy parameters in functions.
- Add a production dependency only with a short rationale in
  `docs/08_DECISION_LOG.md`.
- Keep changes scoped to one vertical slice. Avoid unrelated refactors.
- Do not fabricate market data, provider capabilities, expected returns, or
  broker guarantees in documentation.

## Required workflow for every implementation task

1. Read `docs/PROJECT_STATUS.md`, the task prompt, and relevant normative docs.
2. Inspect the current implementation and tests before proposing edits.
3. State assumptions and produce a short plan for non-trivial work. Use
   `PLANS.md` for changes spanning multiple components.
4. Implement the smallest end-to-end slice that satisfies the task.
5. Add or update tests for normal behavior and failure behavior.
6. Run baseline verification plus any task-specific checks.
7. Review the diff for accidental live-trading paths and missing fail-closed
   behavior.
8. Update `docs/PROJECT_STATUS.md` and, when appropriate,
   `docs/08_DECISION_LOG.md`.
9. Report what changed, commands run, evidence, and remaining limitations.

## Baseline commands

Run from the repository root.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m catalyst.demo
```

When development dependencies are installed, also run:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=catalyst --cov-report=term-missing
```

Do not claim a check passed unless its command actually completed successfully.
If an optional tool is unavailable, report that fact and still run the standard
library baseline.

## Testing expectations

- Unit tests: state transitions, each strategy gate, risk locks, sizing, and
  invalid data.
- Contract tests: each adapter must satisfy its port without real network use.
- Replay tests: deterministic inputs produce byte-for-byte stable decisions.
- Integration tests: synthetic event to demo order and journal record.
- Failure tests: real account, stale data, spread spike, missing stop, broker
  disconnect, duplicate event, and daily lock.
- Unit tests must not use network access, real MT5, current time, or randomness
  without a fixed seed.

## Definition of done

A task is complete only when:

- requested behavior is implemented;
- relevant tests cover success and rejection paths;
- baseline verification passes;
- no demo-only invariant was weakened;
- public behavior and configuration are documented;
- `docs/PROJECT_STATUS.md` identifies the next concrete task;
- no secrets, generated caches, databases, logs, or broker terminal files are
  included in the repository.

## Code review rules

Flag as blocking:

- any path capable of trading a real account;
- any order without an initial protective stop;
- float-based money or risk arithmetic;
- divergent strategy rules between replay and demo execution;
- network or clock dependence in unit tests;
- swallowed exceptions in risk or execution code;
- default-allow behavior after missing or invalid data;
- mutable global trading state;
- undocumented strategy parameter changes;
- performance claims unsupported by out-of-sample evidence after costs.
