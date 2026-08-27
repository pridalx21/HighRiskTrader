# Development plan

Each phase is a vertical slice with its own prompt in `prompts/`. Complete and
verify one phase before starting another.

## Phase 0: Baseline and contract

- Verify starter tests and demo.
- Initialize Git and record the baseline commit.
- Confirm Python and operating-system assumptions.
- Resolve contradictions and update project status.
- Do not add product features.

## Phase 1: Domain and deterministic decision core

- Harden domain validation and reason codes.
- Complete state-machine transition tests.
- Add broker contract metadata and exact volume-step rounding.
- Add configuration loading from TOML into validated domain config.
- Add deterministic configuration hashing.
- Maintain zero external runtime dependencies in core.

Exit: all strategy/risk decisions can be evaluated from immutable inputs.

## Phase 2: Replay and feature builder

- Implement raw tick/bar fixture format.
- Build pre-event range, robust spread baseline, breakout, retest, and
  cross-asset vote features.
- Implement event replay clock and deterministic ordering.
- Add bid/ask cost model, commission, slippage, latency, missed and partial fills.
- Implement exit engine identically for replay/demo.
- Export complete JSON replay report.

Exit: synthetic and historical fixtures pass end-to-end replay acceptance.

## Phase 3: Event data and journal

- Implement strict CSV calendar adapter.
- Select and document one structured provider only if needed.
- Normalize event revisions without using them for v1 direction.
- Implement SQLite journal, schema migrations, idempotency, and single-instance
  lock.
- Implement restart reconciliation state.

Exit: event schedule and every decision survive restart without duplication.

## Phase 4: MT5 demo adapter

- Run on Windows with optional `MetaTrader5` package.
- Verify terminal, account, and explicit demo mode at startup/reconnect/order.
- Normalize symbol metadata and calculate broker-correct volume.
- Implement `order_check`, bracket request, retcode mapping, and reconciliation.
- Add shadow mode before automatic demo orders.
- Test disconnect, timeout, partial fill, stale data, and kill switch.

Exit: demo-only end-to-end order lifecycle passes contract and soak tests.

## Phase 5: Operator dashboard

- Read-only status, event timeline, state, four gates, risk, and journal.
- Explicit `AUTO-DEMO` arm/disarm command through a narrow control port.
- Kill switch independent of LLM and numeric form fields.
- Trade/rejection explanations from stored deterministic reason codes.
- Replay inspection and report export.

Exit: operator can understand and safely control the demo system on one page.

## Phase 6: Validation harness

- Chronological walk-forward runner.
- Fixed-seed bootstrap/Monte-Carlo.
- Cost and delay stress tests.
- Breakdown by event, instrument, period, and regime.
- Concentration and largest-winner analysis.
- Demo versus replay execution comparison.

Exit: an evidence pack supports a continue, revise, or stop decision.

## Post-MVP only

- MQL5 guardian.
- n8n reporting workflows.
- OpenClaw read-only analyst.
- Opening-range strategy.
- Pyramiding into locked-profit winners.
- Any live-trading design.

