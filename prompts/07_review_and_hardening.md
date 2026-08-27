# Prompt 07: Final MVP review and hardening

## Goal

Review the complete MVP as a safety-critical demo system, repair verified
defects, and produce a release candidate with reproducible evidence.

## Review lenses

1. Strategy and risk conformance.
2. Real-account and secret exposure.
3. Fail-open behavior and unknown states.
4. Replay/demo divergence.
5. Idempotency, restart, and reconciliation.
6. Bid/ask, costs, rounding, and contract metadata.
7. Clock, timezone, stale-data, and event identity failures.
8. Test determinism and missing negative tests.
9. Dashboard/control separation.
10. Documentation and operational recoverability.

## Required work

- Trace one accepted and every major rejected flow end to end.
- Run full static checks, tests, replay fixtures, and demo shadow soak test.
- Review dependencies and generated artifacts.
- Remove dead code and unsafe debug paths.
- Produce a release checklist and known-limitations report.
- Confirm every acceptance item in `docs/06_TESTING_AND_ACCEPTANCE.md` with
  concrete evidence or mark it incomplete.

## Constraints

- Do not reduce a threshold merely to make tests pass.
- Do not enable live trading.
- Do not add features during hardening.
- No acceptance claim without command output, journal evidence, or report.

## Done when

- all critical and high issues are fixed or the release is explicitly blocked;
- verification is reproducible from a clean checkout;
- demo-only boundary is proven;
- runbooks cover start, stop, restart, incident, and kill switch;
- final status clearly identifies go/no-go for extended demo validation.

