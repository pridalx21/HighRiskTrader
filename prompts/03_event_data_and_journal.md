# Prompt 03: Add strict event ingestion and persistent journal

## Goal

Create an auditable local event schedule and append-only decision/order journal
that survive restart without duplicate event orders.

## Required work

- Implement strict `config/events.example.csv` ingestion.
- Reject naive timestamps, duplicates, bad importance, and missing identifiers.
- Preserve original rows and normalized records.
- Add a SQLite journal with schema migrations and WAL mode.
- Persist decisions, gate reasons, config hash, orders, fills, state transitions,
  heartbeats, and idempotency keys.
- Add a single-instance lock.
- Implement restart reconciliation interfaces without MT5-specific logic.
- Add export of a complete event decision audit bundle.
- Add adapter contract tests and simulated crash/restart tests.

## Constraints

- No arbitrary HTML scraping.
- A paid/live provider is optional and may not block the CSV slice.
- Unknown journal state disarms execution.
- An order timeout never triggers blind resubmission.
- Secrets and raw credentials never enter the journal.

## Done when

- repeated event ingestion is idempotent;
- restart cannot produce duplicate order intent;
- migration and corruption failure paths are tested;
- audit export reconstructs one event from inputs to outcome;
- baseline and new tests pass;
- status and decision log are current.

