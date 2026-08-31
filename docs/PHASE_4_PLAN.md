# Phase 4 implementation plan

## Outcome

CATALYST can connect to one explicitly configured MetaTrader 5 demo account on
Windows, normalize broker/account metadata, operate in read-only shadow mode,
and submit a demo order only after a separate per-process arm action. Restart
reconciliation can inspect MT5 orders without creating or retrying one.

## Safety boundary

- Demo only. Real, contest, unknown, mismatched login, or mismatched server fails closed.
- The adapter starts disarmed after every process start and disconnect.
- Configuration permission and an explicit runtime arm are both required.
- Every order request contains the initial protective stop.
- `order_send` is called at most once for one durable submission attempt.
- `None`, exceptions, or missing broker order identity after submission are uncertain
  outcomes and must flow through Phase 3 reconciliation; they are never retried blindly.
- Unit and CI tests use a fake MT5 module and require no terminal or credentials.

## Implemented slice

1. Lazy MT5 boundary
   - No MetaTrader5 import or connection occurs at module import time.
   - A fake module can satisfy the contract in CI.
2. Connection and account verification
   - Bounded connection attempts.
   - Exact configured login and server verification.
   - Positive `ACCOUNT_TRADE_MODE_DEMO` check on connect, snapshot, arm, contract lookup,
     reconciliation, and immediately before submission.
3. Explicit broker economics
   - Logical-to-broker symbol mapping is mandatory.
   - MT5 supplies tick size/value, contract size, currencies, and volume constraints.
   - Commission/slippage allowance and any currency conversion are explicit configuration;
     the adapter does not invent them.
4. Demo execution
   - Automatic execution is disabled by default.
   - Runtime arming is explicit and non-persistent.
   - Volume is checked against broker minimum/maximum/step.
   - `order_check` precedes the single `order_send` call.
   - A deterministic comment derived from the decision id supports reconciliation.
5. Restart reconciliation
   - Read-only open/history lookup uses the deterministic comment and mapped symbol.
   - Found orders resolve through the existing Phase 3 reconciliation protocol.
   - Missing or unreadable broker history remains unresolved and disarmed.

## Still required for a broker-specific smoke test

The repository deliberately does not contain these operator-specific values:

- Windows `terminal64.exe` path;
- MT5 demo login and exact demo server name;
- logical-to-broker symbol mapping for the selected broker;
- verified per-symbol commission/slippage assumptions and currency conversions;
- representative `symbol_info` and order retcodes from that demo server.

No password should be committed or printed. The first real-terminal run must remain shadow-only.
An actual demo order is an opt-in smoke test and is not required by CI.

## Verification target

- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest --cov=catalyst --cov-report=term-missing`
- `bash scripts/verify.sh`
- existing deterministic replay hash remains unchanged
