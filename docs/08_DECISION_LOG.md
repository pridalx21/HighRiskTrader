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

## Template

```text
## ADR-NNN: Title

- Status: Proposed | Accepted | Superseded | Rejected
- Context:
- Decision:
- Consequences:
- Supersedes:
```
