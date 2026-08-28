# Decision log

Record architecture, strategy, risk, dependency, and provider decisions here.
Never rewrite an accepted entry; append a superseding decision.

## ADR-001: Python functional core with MT5 adapter

- **Status:** Accepted
- **Context:** Structured event data, replay, testing, and analysis are easier in
  Python, while MT5 is useful for broker-specific demo prices and execution.
- **Decision:** Keep strategy and risk in dependency-light Python. Treat MT5 as
  an adapter. Use one core pipeline in replay and demo.
- **Consequences:** A custom replay engine is required. The later adapter must
  model broker contract metadata and demo-account verification carefully.

## ADR-002: One Event Reaction Retest strategy

- **Status:** Accepted
- **Context:** Multiple strategies would multiply parameters and obscure whether
  the basic hypothesis works.
- **Decision:** MVP supports one event-conditioned, price-confirmed retest.
- **Consequences:** Low trade frequency is expected and is not a reason to add
  setups before validation.

## ADR-003: Demo-only hard boundary

- **Status:** Accepted
- **Context:** The system is unvalidated and the user explicitly wants demo
  testing first.
- **Decision:** Reject real and unknown account modes. No live bypass exists.
- **Consequences:** Any later live phase requires a separate approved project
  milestone and threat/risk review.

## ADR-004: No LLM in numeric decision path

- **Status:** Accepted
- **Context:** LLM output is probabilistic, hard to replay exactly, and exposed
  to untrusted news prose.
- **Decision:** LLMs may summarize and explain immutable records but cannot set
  direction, entry, stop, size, or submit orders.
- **Consequences:** Structured event data and deterministic price rules are
  required.

## ADR-005: Standard-library-compatible starter core

- **Status:** Accepted
- **Context:** The starter should verify immediately without MT5 or package
  installation.
- **Decision:** Initial domain, pipeline, fake broker, and tests use Python's
  standard library. MT5 and UI dependencies are optional extras.
- **Consequences:** Persistence and UI enter in later vertical slices.

## ADR-006: Strict TOML configuration and canonical decision hash

- **Status:** Accepted
- **Context:** Replay and demo must prove that they used identical strategy,
  timing, risk, and execution settings. Permissive parsing or independent state
  and strategy timing objects could silently diverge.
- **Decision:** Parse the exact checked-in TOML schema with `tomllib`, reject
  missing/unknown keys and safety relaxation, construct one immutable runtime
  configuration, and hash its decision-affecting canonical JSON with SHA-256.
- **Consequences:** Every accepted or rejected pipeline decision carries the
  configuration hash. Logging and storage paths are excluded because they do
  not affect numeric decisions.

## ADR-007: Explicit broker contract sizing inputs

- **Status:** Accepted
- **Context:** A linear `value_per_price_unit = 1` assumption cannot represent
  broker tick economics, currency conversion, or volume limits safely.
- **Decision:** Require immutable broker contract metadata at the shared
  pipeline boundary. Calculate base stop loss from tick size/value and currency
  conversion, round positive volume down to the broker step, and then reject if
  commission and slippage make recalculated maximum loss exceed permitted risk.
  Contract size is captured and validated for broker reconciliation; the
  broker-provided tick value remains the monetary value per tick and volume
  unit and is not multiplied by contract size a second time.
- **Consequences:** Missing metadata, unknown conversion, off-tick prices,
  below-minimum/above-maximum volume, and post-cost over-risk plans fail closed.
  The MT5 adapter must normalize and verify these fields in Phase 4.

## ADR-008: Standard-library JSON replay boundary for Phase 2

- **Status:** Accepted
- **Context:** A reconstructable replay is needed before a historical provider,
  licensed dataset, or persistence schema has been selected. Adding Parquet now
  would create an unneeded production dependency and imply a premature schema.
- **Decision:** Use strict checked-in JSON fixtures with UTC strings and decimal
  strings, and export canonical JSON reports. Defer Parquet and SQLite to the
  provider and journal slices.
- **Consequences:** The Phase 2 baseline stays install-free and byte-stable.
  The domain remains storage-independent; a future adapter may add Parquet only
  with a dependency rationale and contract tests.

## ADR-009: Deterministic v1 market feature definitions

- **Status:** Accepted
- **Context:** Breakout, retest, reclaim, ATR, and related-market votes must be
  reconstructable and cannot depend on subjective chart reading.
- **Decision:** Use the first post-shock midpoint outside the highest-ask/
  lowest-bid range, a first outside retest within one tick of the broken edge,
  and the next outside tick as hold. Any full return inside invalidates; an
  opposite-side break is a whipsaw. Median pre-event spread, mean bid/ask-mid
  true range, and explicit polarity/minimum-move votes are stored as evidence.
- **Consequences:** The same raw input has one ordered result. These are starting
  hypotheses, not evidence of edge; changes require strategy versioning.

## ADR-010: Executable-side deterministic replay fills

- **Status:** Accepted
- **Context:** Midpoint fills omit the spread and overstate achievable execution.
- **Decision:** Long entries fill at ask, short entries at bid, long exits at
  bid, and short exits at ask. The first quote after explicit latency is used;
  adverse-slippage limits, deterministic rejection, missed quotes, volume-step
  partial fills, and commission are recorded without randomness.
- **Consequences:** Every fill or skipped fill is auditable and reproducible.
  This model is deliberately conservative but is not a broker-fill guarantee.
  Contract commission is normalized to a total round-trip amount per volume so
  risk sizing and replay P&L use the same cost meaning.
  The replay adverse-slippage limit cannot exceed the contract allowance used
  for worst-case sizing.

## ADR-011: Conservative Phase 2 intraday exit scope

- **Status:** Accepted
- **Context:** The strategy mentions partial realization and trailing only
  after replay validation, while hard protection and intraday closure are
  immediate safety requirements.
- **Decision:** Share one pure exit engine for replay and later demo adapters.
  Precedence is emergency, protective stop, complete range reclaim, then UTC
  session cutoff. Stops may tighten but never widen. Partial `+2R` realization
  and trailing are disabled.
- **Consequences:** Phase 2 has deterministic same-day closure without inventing
  unvalidated optimization parameters. Enabling partial/trailing requires a
  versioned decision and new replay evidence.

## ADR-012: Self-contained strict manual event CSV

- **Status:** Accepted
- **Context:** The normalized event contract requires status and eligible
  logical symbols. Inferring either from event prose or currency would make the
  same row environment-dependent and difficult to audit.
- **Decision:** Require one exact CSV header with explicit UTC time,
  `LOW|MEDIUM|HIGH` importance, explicit event status, pipe-delimited logical
  symbols, `manual_csv` source, and optional finite decimal strings. Preserve
  every ordered source field next to the normalized immutable event.
- **Consequences:** Calendar edits fail loudly when their schema or identity is
  ambiguous. A provider adapter may use a different raw contract later, but it
  must produce the same normalized and source-preserving boundary.

## ADR-013: Append-only SQLite WAL journal

- **Status:** Accepted
- **Context:** Phase 3 needs restart-safe audit and idempotency while keeping the
  standard-library baseline and local MVP operations.
- **Decision:** Use one local SQLite database with WAL, full synchronization,
  foreign keys, checksummed forward migrations, immutable-table update/delete
  triggers, an operating-system single-instance file lock, and a SHA-256 chain
  over canonical entries. Store source/normalized events separately from the
  append-only lifecycle stream.
- **Consequences:** Journal corruption, schema mismatch, a second process, or an
  unavailable write fails closed. SQLite is an adapter choice; the domain and
  strategy remain persistence-independent. Parquet remains deferred.

## ADR-014: Reserve before submit and never retry uncertainty

- **Status:** Accepted
- **Context:** A crash or timeout between broker acceptance and local
  acknowledgement can make an order outcome unknowable. Automatic retry could
  duplicate risk.
- **Decision:** Require the event and full decision to be journaled, then insert
  the unique stable idempotency key before the only broker submission attempt.
  Treat reserved, submitting, timeout, not-found, and unknown states as
  reconciliation-required. Reconciliation is read-only and never arms or
  resubmits; only a positively found broker order can close the uncertainty.
- **Consequences:** Some valid opportunities may require manual review or be
  missed after an incident. This conservative loss of availability is accepted
  to prevent duplicate event exposure.

## Template

```text
## ADR-NNN: Title

- Status: Proposed | Accepted | Superseded | Rejected
- Context:
- Decision:
- Consequences:
- Supersedes:
```
