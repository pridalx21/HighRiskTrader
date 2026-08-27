# Prompt 04: Implement the MT5 demo adapter

## Goal

Connect the validated core to one MetaTrader 5 demo account on Windows, first in
shadow mode and then through explicitly armed automatic demo execution.

## Before coding

Confirm the operator has supplied:

- MT5 terminal path;
- demo server and login through environment configuration;
- logical-to-broker symbol mapping;
- example `symbol_info`, account mode, and order retcodes from the demo server.

Do not ask for or print the password in chat. Stop if account mode cannot be
positively verified as demo.

## Required work

- Implement MT5 connection lifecycle and bounded reconnect.
- Verify explicit demo account mode on startup, reconnect, and pre-submit.
- Normalize ticks, bars, account state, positions, orders, and symbol metadata.
- Use broker tick size/value, contract size, currency, and volume steps for size.
- Implement order validation, `order_check`, bracket submission, retcode mapping,
  idempotency, fill handling, and reconciliation.
- Start with shadow decisions and compare intended versus broker-observed data.
- Require explicit operator arming before automatic demo orders.
- Implement disconnect, timeout, partial-fill, stale-data, and kill-switch tests
  using fakes plus a separate opt-in demo smoke test.

## Constraints

- No real or unknown account may pass.
- No order without an initial broker-side stop.
- No automatic retry after ambiguous submission.
- Unit/CI tests must not need MT5 or credentials.
- Do not place an actual demo order merely to prove installation unless the
  operator explicitly asks to run the opt-in smoke test.

## Done when

- adapter contracts pass with fakes;
- verified demo shadow mode runs and journals correctly;
- opt-in demo order lifecycle is reproducible and safely bounded;
- reconnect and restart reconciliation are proven;
- all non-demo tests remain green;
- runbook, status, and decisions are updated.

