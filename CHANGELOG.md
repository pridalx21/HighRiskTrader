# Changelog

## Unreleased

- Added strict, source-preserving manual CSV event ingestion.
- Added checksummed append-only SQLite WAL journal and single-instance lock.
- Added durable order idempotency, no-retry timeout handling, and restart
  reconciliation ports.
- Added canonical event audit bundles and corruption/migration failure checks.
- Restored the configured Ruff, formatting, mypy, and coverage CI gates.

## 0.1.0 - Starter

- Added demo-only project contract and Codex workflow.
- Added deterministic domain, strategy, state-machine, and risk skeleton.
- Added fake broker, end-to-end decision pipeline, and baseline tests.
- Added ordered implementation prompts and acceptance criteria.
