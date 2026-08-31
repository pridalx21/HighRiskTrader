# Phase 6 implementation plan

## Outcome

CATALYST can turn frozen historical/demo observations into a deterministic,
hashed validation evidence pack without changing strategy or risk parameters.

## Implemented boundary

- strict JSON observations preserve IDs, UTC timestamps, event family,
  instrument, regime, source, qualification/trade state, after-cost R, optional
  intended/actual demo slippage, and explicit exclusions;
- chronological development/untouched-evaluation split;
- rolling walk-forward evaluation;
- event-family and instrument holdouts plus event/instrument/year/regime
  breakdowns;
- pessimistic cost/spread/slippage, execution-delay, broker-rejection, and
  missed-winning-fill stresses;
- fixed-seed bootstrap/Monte-Carlo for expectancy distribution, drawdown, and
  monthly loss-cap breach probability;
- concentration, largest-winner, losing-streak, drawdown, profit-factor, and
  no-trade metrics;
- intended-versus-actual demo slippage comparison;
- machine-readable canonical JSON, concise Markdown, and SHA-256 manifest;
- explicit `CONTINUE`, `REVISE`, or `STOP` verdict with blocking reasons.

## Promotion gates

`CONTINUE` requires at least 100 untouched evaluation trades, positive
out-of-sample expectancy after costs, profit factor above 1.20, no single winner
above 20% of evaluation profit, no single event family above 50% of profit,
comparable demo execution evidence, and at least eight unattended demo weeks.

The harness never tunes parameters to satisfy these gates. Failing evidence
returns `REVISE` or `STOP`; it does not increase risk.

## Commands

```bash
catalyst-validate INPUT.json OUTPUT_DIR --strategy-version VERSION
```

`config/validation.example.json` is synthetic CI input only. It is not market
evidence and must never be cited as strategy profitability.
