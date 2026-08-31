# Security and operations

## Trust boundary

Only the deterministic Python core and verified broker adapter may participate
in order creation. The dashboard, notifications, n8n, OpenClaw, LLM summaries,
and web/news text are untrusted presentation or operations inputs.

## Secrets

- Use environment variables or an operating-system secret store.
- Keep `.env`, terminal profiles, databases, and logs out of Git.
- Do not place credentials in TOML examples, tests, screenshots, prompts, or
  issue descriptions.
- Redact login IDs and broker response fields in reports where unnecessary.
- Rotate credentials if they appear in a commit or chat.

## Demo-account verification

Startup must obtain account mode from the broker API and compare it to the
broker's explicit demo constant. Configuration such as `DEMO_ONLY=true` is not
sufficient by itself. Unknown, contest, or real modes are rejected.

Account mode must be rechecked after reconnect and before order submission.

## Network behavior

- Core unit tests use no network.
- Calendar and broker adapters use explicit timeouts and bounded retries.
- Retries are safe only for idempotent reads.
- An order timeout triggers reconciliation, not automatic resubmission.
- Use TLS endpoints supplied by the selected provider; do not disable
  certificate verification.

## Startup sequence

1. Load and validate configuration.
2. Open journal and acquire the single-instance lock.
3. Connect to MT5 and verify demo account, currency, and permissions.
4. Reconcile positions, orders, and recent history against local state.
5. Load event schedule and verify UTC timestamps.
6. Warm market features and spread baselines.
7. Start in `DISARMED` state.
8. Require explicit operator activation for automatic demo orders.

## Shutdown sequence

1. Disarm new intents.
2. Persist final state and heartbeat.
3. Reconcile managed demo orders and positions.
4. Follow configured policy for open intraday positions.
5. Close adapters cleanly and write shutdown audit record.

## Incident behavior

| Incident | Required action |
| --- | --- |
| Market data stale | Reject setup; lock affected event |
| Calendar unavailable | Do not arm new events |
| MT5 disconnect | Disarm; reconnect; re-verify account; reconcile |
| Journal unavailable | Disarm; do not trade without audit state |
| Unknown broker retcode | Lock execution and require review |
| Duplicate order uncertainty | Query orders/history; never blind retry |
| Clock drift | Disarm until trusted time is restored |
| Dashboard failure | Core stays safe; kill switch remains available separately |
| LLM/n8n/OpenClaw failure | No effect on core trading state |

## Observability

Use structured logs with event IDs, decision IDs, idempotency keys, strategy
version, state transitions, gate codes, broker retcodes, and timing. Avoid raw
secrets and unlimited provider payloads.

Minimum health indicators:

- core heartbeat;
- MT5 connection and account mode;
- latest market-data timestamp by symbol;
- latest calendar refresh;
- journal write status;
- armed event and state;
- auto-demo armed/disarmed;
- active positions, pending orders, and risk locks.

## Local journal boundary

Phase 3 permits exactly one process to open the journal through an operating-
system file lock. SQLite must report WAL mode, pass schema and integrity checks,
and verify its canonical entry hash chain before the journal becomes healthy.
Business records have update/delete rejection triggers. Journal APIs reject
credential-shaped key names recursively. Failure of any of these checks keeps
execution disarmed; deleting a lock file is never a recovery procedure while a
process may still be running.

## Post-MVP integrations

- n8n: daily schedule import, backup, and report delivery only.
- OpenClaw: read-only journal explanations; no broker credentials or order tool.
- MQL5 guardian: independent heartbeat, maximum-volume, required-stop, and
  emergency-close checks after Python demo stability.
