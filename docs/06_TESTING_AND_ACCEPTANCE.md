# Testing and acceptance

## Purpose

Testing must answer two separate questions:

1. Does the software obey its rules?
2. Does the strategy show an out-of-sample edge after realistic costs?

The first is mandatory for MVP completion. The second requires historical and
forward evidence and cannot be inferred from passing unit tests.

## Test pyramid

### Unit tests

Fast, deterministic, standard-library-compatible tests for:

- domain validation;
- every event-state transition;
- each strategy gate independently;
- all-green setup and every rejection path;
- demo-only account enforcement;
- daily and consecutive-loss locks;
- stop direction and position sizing;
- rounding down to broker volume step;
- duplicate/idempotency behavior;
- exit and kill-switch state when implemented.

### Contract tests

Every adapter receives a reusable contract suite:

- market data normalizes timestamps and bid/ask correctly;
- calendar rejects invalid and duplicate events;
- broker rejects non-demo accounts and missing stops;
- journal append/read reproduces the complete decision;
- restarts reconcile rather than blindly resubmit.

No contract test uses a real-money account.

### Replay tests

- Fixed fixtures with known pre-event ranges and retests.
- Same input yields the same ordered decision records.
- Costs include spread, commission, slippage, rejection, partial fills, and
  latency assumptions.
- Replay uses executable bid/ask sides, not midpoint fantasy fills.
- A decision generated in replay matches the live-demo pipeline fields.

The Phase 2 acceptance suite fixes seven synthetic cases: long pass, short
pass, whipsaw, stale data, spread spike, missing confirmation, and late setup.
It asserts the exact decision code, direction, execution status, and exit
reason. Focused tests additionally cover equal-timestamp ordering, latency,
adverse-slippage misses, deterministic rejection, partial-fill rounding,
executable bid/ask sides, hard stops, range reclaim, emergency precedence,
cutoff, stale exit quotes, and the stop-widening prohibition. Repeated complete
reports must be byte-identical.

### Demo forward tests

- Demo balance set to approximately CHF 1,000.
- Run in signal-only shadow mode before enabling automatic demo orders.
- Record intended and actual order timing, spread, slippage, and broker retcodes.
- Test disconnects, restarts, stale data, duplicate events, and kill switch.
- Do not manually skip losing signals or add winning signals after the fact.

## Baseline commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m catalyst.demo
PYTHONPATH=src python -m catalyst.replay_demo
```

With development tools installed:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=catalyst --cov-report=term-missing
```

## MVP software acceptance

All must be true:

- core tests and adapter contract tests pass;
- real or unknown account mode is rejected in tests and demo startup;
- order requests always contain a protective stop;
- replay and demo use the same pipeline entry point;
- every gate and lock produces a reason code;
- duplicate order intents are prevented across process restart;
- kill switch works during simulated dependency failures;
- dashboard cannot construct or mutate numeric plans;
- secrets and broker terminal files are absent from Git;
- operator runbook covers startup, shutdown, recovery, and incident export.

## Strategy validation protocol

Do not optimize and evaluate on the same events.

1. Freeze strategy version and small parameter set.
2. Split data chronologically into development and untouched evaluation windows.
3. Use rolling walk-forward evaluation across different volatility/rate regimes.
4. Hold out at least one event family or market as a robustness check.
5. Re-run with pessimistic costs, delayed entry, and missed fills.
6. Bootstrap/Monte-Carlo the ordered trade outcomes with fixed seeds.
7. Report distributions, not one equity curve.

Required metrics include:

- trade count and no-trade count;
- expectancy in R after costs;
- average win and average loss in R;
- profit factor;
- maximum drawdown and drawdown duration;
- longest losing streak;
- monthly loss-cap breach probability;
- result by event family, instrument, year, and volatility regime;
- contribution of the five largest trades;
- intended versus actual demo slippage.

## Example promotion gates

These are conservative review gates, not return promises:

- positive out-of-sample expectancy after pessimistic costs;
- profit factor greater than 1.20 out of sample;
- at least 100 independent qualified setups across multiple event families;
- no single trade supplies more than 20% of total out-of-sample profit;
- no single event family supplies more than 50% of total profit without an
  explicit narrower-system decision;
- demo behavior matches replay assumptions within documented tolerance;
- at least 8–12 weeks of unattended demo operation without safety violation.

Failure of a gate means revise or stop. It does not justify increasing leverage
or optimizing more parameters.
