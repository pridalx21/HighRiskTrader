# Phase 3 implementation plan

## Outcome

CATALYST can ingest an auditable manual event calendar and persist every event,
decision, order intent, execution result, fill, state transition, heartbeat, and
reconciliation result in a local append-only SQLite journal. A restart cannot
submit a previously reserved order intent again.

## Context

- Normative documents: `docs/04_RISK_POLICY.md`, `docs/03_STRATEGY_SPEC.md`,
  `docs/02_ARCHITECTURE.md`, `docs/06_TESTING_AND_ACCEPTANCE.md`,
  `docs/01_MVP_SCOPE.md`, `docs/05_DATA_CONTRACTS.md`, and
  `docs/07_SECURITY_AND_OPERATIONS.md`.
- Task contract: `prompts/03_event_data_and_journal.md`.
- Existing boundaries: `EconomicEvent`, `PipelineDecision`, `TradePlan`,
  `EventFeedPort`, `BrokerPort`, and canonical serialization.
- Current status item: strict CSV event ingestion, persistent idempotency,
  append-only journal, and restart reconciliation.

## Constraints and non-goals

- The system remains demo-only and starts disarmed.
- No MT5, provider network, HTML scraping, database server, or new production
  dependency enters this phase.
- No timeout or uncertain submission may trigger an automatic retry.
- Journal or reconciliation uncertainty keeps execution disarmed.
- The journal must not accept credential-shaped fields.
- Strategy, sizing, and exit behavior remain unchanged.

## Assumptions

- The checked-in CSV is the initial authoritative schedule.
- CSV rows explicitly carry status and eligible logical symbols; the adapter
  does not infer either from prose or currency.
- SQLite is local to one CATALYST process and uses WAL plus an operating-system
  file lock.
- A later MT5 adapter will implement the broker reconciliation protocol.

## Implementation slices

1. Strict calendar adapter
   - Parse one exact UTF-8 CSV schema.
   - Reject naive/non-UTC timestamps, duplicate IDs, unknown enum values,
     malformed optional decimals, missing identifiers, and invalid symbols.
   - Preserve ordered source fields alongside normalized immutable events.
2. Durable journal
   - Apply checksummed schema migrations and require WAL.
   - Store immutable event records and a hash-chained append-only entry stream.
   - Reserve unique order idempotency keys before submission.
   - Reject updates and deletes with database triggers.
3. Safe execution and restart
   - Submit only after a durable reservation.
   - Record timeout as uncertain and never retry it automatically.
   - Reconcile unresolved intents through a broker-neutral protocol.
   - Keep unknown or not-found broker state disarmed.
4. Audit and verification
   - Export one canonical, hashed event audit bundle.
   - Test repeated import, single-instance locking, migration mismatch,
     corruption, credential rejection, crash/restart, and reconciliation.

## Verification

- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `PYTHONPATH=src python -m catalyst.demo`
- `PYTHONPATH=src python -m catalyst.replay_demo`
- `python -m compileall -q src tests scripts`
- Optional Ruff, formatting, mypy, pytest, and coverage checks when installed.

## Safety review

- The durable executor positively rechecks broker connectivity and demo mode
  after intent reservation and immediately before the only submission call.
  Real, unknown, disconnected, or unreadable account state never reaches it.
- Every durable submission accepts only an existing `TradePlan`, whose initial
  protective stop invariant is immutable.
- Duplicate, timed-out, corrupt, locked, or unreconciled journal state rejects
  further submission.
- Stored canonical values retain UTC timestamps and decimal strings.
- Replay and demo strategy code is untouched.
- Journal payload validation rejects secret-bearing key names.

## Documentation and decisions

- Append the accepted CSV and SQLite boundaries to `docs/08_DECISION_LOG.md`.
- Update `docs/05_DATA_CONTRACTS.md`, `README.md`, `CHANGELOG.md`, and
  `docs/PROJECT_STATUS.md` after verification.
