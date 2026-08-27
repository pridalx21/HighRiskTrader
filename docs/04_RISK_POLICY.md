# Risk policy

This is the highest-priority project specification. The software must reject a
trade whenever compliance with this policy cannot be proven.

## Capital model

- The intended future speculative allocation is one fresh CHF 1,000 risk
  capsule per month.
- The MVP uses a demo account configured to approximately CHF 1,000.
- There is no automatic refill during a month.
- A future profit sweep is operationally separate from the trading engine.
- The system never assumes a stop guarantees the exact planned loss.

## Risk unit

Default:

```text
1R = 5% of current account equity at decision time
```

All calculations use `Decimal`. Broker volume is rounded down to a valid step.
Rounding up is forbidden.

The MVP software hard cap is 10% per initial trade, 3R daily loss, three
consecutive losses, and one active risk cluster. Configuration may tighten
these limits but may not raise them without an explicitly approved risk-policy
revision and code change.

## Hard limits

| Limit | Default | Behavior when reached |
| --- | ---: | --- |
| Account mode | Demo only | Lock and reject |
| Initial risk per trade | 1R | Reject greater risk |
| Daily loss limit | 3R based on day-start equity | Lock for day |
| Consecutive losses | 3 | Lock for day |
| Concurrent risk clusters | 1 | Reject new setup |
| Trades per event cluster | 1 | Reject duplicate |
| Missing protective stop | Never allowed | Reject order |
| Averaging down | Never allowed | Reject modification/addition |
| Overnight exposure | Never allowed | Force documented cutoff exit |
| Stale/ambiguous data | Never allowed | Reject setup |

## Position sizing

For a simple linear instrument:

```text
risk_amount = equity * risk_fraction
stop_distance = abs(entry - stop)
raw_quantity = risk_amount / (stop_distance * value_per_price_unit)
quantity = floor_to_broker_step(raw_quantity)
```

The MT5 adapter must use broker tick size, tick value, contract size, currency
conversion, minimum volume, maximum volume, and volume step rather than assume
`value_per_price_unit = 1`.

After rounding and a pessimistic cost/slippage allowance, recalculated maximum
loss must be less than or equal to the permitted risk amount. Otherwise reject.

## Daily lock calculation

At day start, record:

```text
day_R = day_start_equity * risk_fraction
daily_loss_limit = 3 * day_R
```

The limit does not shrink after losses or expand after intraday gains. Realized
loss, fees, and any open worst-case risk count toward the lock.

## Correlation

The following examples are one risk cluster during the same macro event:

- US100 and US500 in the same direction;
- EURUSD long and USDCHF short as a shared USD-short expression;
- XAUUSD long plus several USD-short FX positions;
- GER40 and EURUSD when both express the same ECB surprise narrative.

Version 1 avoids correlation math and allows exactly one active cluster.

## Fail-closed conditions

Lock or reject when any of these is true:

- account type cannot be positively identified as demo;
- account currency or symbol conversion is unknown;
- tick value, tick size, contract size, or volume step is missing;
- stop is on the wrong side of entry;
- calculated quantity is zero, non-finite, negative, or above limits;
- data heartbeat exceeds threshold;
- terminal, broker, calendar, or journal is unavailable;
- broker response is unknown, partial, or inconsistent;
- duplicate idempotency key exists;
- local state cannot be reconciled with broker positions and orders;
- system time differs materially from trusted market/event time.

## Forbidden risk behaviors

- martingale;
- grid trading;
- averaging down;
- doubling size after a loss;
- moving a stop farther away;
- removing a stop before position closure;
- treating unrealized profit as permission for unbounded new risk;
- automatically resetting a daily lock;
- ignoring rejected orders and blindly retrying;
- assuming negative-balance protection without verifying broker terms.

## Kill switch

The kill switch must:

1. prevent new intents immediately;
2. cancel pending strategy orders;
3. request closure of managed demo positions;
4. keep monitoring until broker state is reconciled;
5. write an immutable audit record;
6. require an explicit operator action to re-arm.

The kill switch must work without an LLM, n8n, OpenClaw, or the dashboard being
healthy.
