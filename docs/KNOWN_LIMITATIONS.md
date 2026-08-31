# Known limitations

## Software MVP versus strategy evidence

The code-level MVP can be complete while the trading strategy is still
unpromoted. Software acceptance proves deterministic behavior, fail-closed
execution, auditability, and reproducibility. It does not prove profitability.

## Environment-specific verification still required

- The real Windows MT5 shadow smoke command must be run against the operator's
  selected demo server, account, symbols, and contract metadata.
- No real broker terminal is available in CI, so CI uses injected MT5 fakes.
- No actual demo order is placed automatically as an installation test. The
  operator must explicitly choose to run any future opt-in order lifecycle test.

## Validation evidence still required before strategy promotion

- `config/validation.example.json` is synthetic test data only.
- A licensed/authoritative historical data source is not bundled.
- At least 100 untouched evaluation trades/setups meeting the documented
  promotion definition are required.
- At least 8–12 weeks of unattended demo evidence are required by the acceptance
  contract before considering promotion.
- Intended replay costs/fills must be compared with observed demo execution.

Failure to meet these gates means `REVISE` or `STOP`; it is not permission to
loosen the risk policy.

## Calendar

The MVP ships a strict, auditable manual CSV boundary. A network calendar
provider is deliberately not required for the MVP. Provider selection,
licensing, revision semantics, and network timeout behavior remain future work.

## Dashboard

The dashboard module is a presentation/control surface, not an execution
scheduler. Runtime orchestration is intentionally explicit: the application
must supply fresh immutable snapshots and the guarded demo broker/control plane.
The standalone kill switch remains available if the dashboard is unavailable.

## No live trading

There is no supported real-account execution path. The MVP is demo-only. Live
trading design, credentials, operational approval, and legal/broker suitability
are outside this release.
