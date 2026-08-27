# Prompt 06: Build the validation harness

## Goal

Produce an evidence pack that can support a continue, revise, or stop decision
without optimizing on the evaluation data.

## Required work

- Chronological train/development and untouched evaluation partitions.
- Rolling walk-forward evaluation.
- Event-family and instrument holdouts.
- Pessimistic spread, commission, slippage, delay, rejection, and missed-fill
  stress scenarios.
- Fixed-seed bootstrap/Monte-Carlo of trade sequences.
- Metrics from `docs/06_TESTING_AND_ACCEPTANCE.md`.
- Concentration, five-largest-winner, losing-streak, and monthly-cap analysis.
- Intended replay versus actual demo execution comparison.
- Machine-readable data output and a concise Markdown report.

## Constraints

- Freeze strategy version before opening evaluation data.
- Do not tune to pass promotion thresholds.
- Report failed and inconclusive results plainly.
- Do not annualize a short demo period into a return claim.
- Preserve every excluded event and exclusion reason.

## Done when

- the full run is reproducible from a single command;
- raw inputs and output hashes are recorded;
- results are separated by in-sample/out-of-sample/demo;
- sensitivity and concentration risks are visible;
- the report ends with `CONTINUE`, `REVISE`, or `STOP` plus evidence;
- status and decisions are updated.

