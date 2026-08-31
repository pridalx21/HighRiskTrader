# MVP release checklist

## Code and safety

- [x] Demo-only account mode is positively verified by the broker adapter.
- [x] Real/unknown account modes fail closed.
- [x] Initial broker-side protective stop is mandatory.
- [x] Durable order intent is reserved before the only submission attempt.
- [x] Timeout/unknown submission is never blindly retried.
- [x] Restart reconciliation is read-only and never auto-arms.
- [x] Persistent kill-switch latch is enforced directly at the broker boundary.
- [x] Standalone kill-switch command can engage but not clear the latch.
- [x] Dashboard/control plane cannot mutate numeric trade parameters.
- [x] Stale/future dashboard state cannot arm automatic demo execution.
- [x] Control actions require authentication, confirmation, and audit persistence.
- [x] Core strategy/risk remains deterministic and independent of MT5/UI/network.

## Replay and validation

- [x] Replay uses the public decision pipeline.
- [x] Bid/ask evidence and pessimistic execution costs are represented.
- [x] MT5 read-side shadow adapter normalizes ticks, bars, positions, orders,
  fills, and executable-side prices without sending orders.
- [x] Validation has chronological development/evaluation partitions.
- [x] Walk-forward, family/instrument holdouts, regime/year breakdowns exist.
- [x] Cost, delay, rejection, and missed-fill stresses exist.
- [x] Fixed-seed bootstrap/Monte-Carlo is reproducible.
- [x] Machine JSON, Markdown, and SHA-256 manifest are generated.
- [x] Validation verdict is explicit `CONTINUE`, `REVISE`, or `STOP`.

## Automated release verification

The GitHub CI release job must be green for the exact merge candidate and run:

- Ruff lint;
- Ruff format check;
- strict Mypy;
- Pytest with branch coverage >= 85%;
- deterministic demo command;
- seven-scenario replay command;
- synthetic validation evidence-pack command;
- Python compileall;
- tracked-file hygiene check for runtime artifacts/private-key markers.

The exact final test count and coverage are recorded in `PROJECT_STATUS.md` only
after this release candidate passes.

## Operator-machine checks (not CI)

- [ ] Run `catalyst-mt5-shadow-smoke` on Windows against the selected demo
  terminal and record the output.
- [ ] Verify each logical/broker symbol mapping and broker economics against the
  actual demo server.
- [ ] If explicitly desired, run the separate opt-in demo order lifecycle smoke
  test under manual supervision; never use a real account.

## Strategy promotion evidence (not software release blockers)

- [ ] Authoritative/licensed historical observation set prepared.
- [ ] At least 100 untouched evaluation trades/setups satisfy the documented
  promotion definition.
- [ ] Out-of-sample expectancy after costs is positive.
- [ ] Out-of-sample profit factor is above 1.20.
- [ ] No single winner contributes more than 20% of evaluation profit.
- [ ] No single event family contributes more than 50% of evaluation profit.
- [ ] At least 8–12 unattended demo weeks are recorded.
- [ ] Replay execution assumptions are compared against actual demo execution.

These promotion items are intentionally separate. Completing the software MVP
must not be represented as evidence of profitable or live-ready trading.
