# Strategy specification

## Strategy ID

`event_reaction_retest_v1`

This document describes starting hypotheses, not validated edge. Parameter
changes require versioning and an entry in `docs/08_DECISION_LOG.md`.

## Principle

The system does not predict the release and does not trade the first spike. It
observes whether price accepts a move outside a pre-event range, waits for a
retest, and requires related-market confirmation.

## Default parameters

| Parameter | Default | Meaning |
| --- | ---: | --- |
| Pre-arm window | 30 minutes | Begin capturing event context |
| Pre-event range | 30 minutes | Highest ask and lowest bid before release |
| Shock window | 90 seconds | Absolute no-trade period after release |
| Entry deadline | 15 minutes | Setup expires after release |
| Minimum related markets observed | 2 | Prevent confirmation from one market |
| Minimum confirmations | 2 | Required votes in the candidate direction |
| Maximum spread multiple | 2.5x | Current spread versus robust baseline |
| Maximum data age | 2.0 seconds | Fail closed beyond this age |
| One setup per event cluster | Yes | Prevent correlated duplicate bets |
| Intraday only | Yes | No overnight holding |

These values are deliberately few. Do not optimize broad grids of values.

## Pre-event preparation

For each eligible event:

1. Map the event to a small logical instrument cluster.
2. Capture the 30-minute pre-event high and low from bid/ask-aware data.
3. Calculate a robust median spread baseline from the same broker and session.
4. Record ATR or another volatility scale for reporting and exit management.
5. Verify market open status and contract metadata.
6. Ensure there is no position or submitted setup for the same risk cluster.

## Gate 1: Catalyst

Pass only when:

- event importance equals `HIGH`;
- event identifier and scheduled UTC timestamp are present;
- the current time is from shock-window end through entry deadline;
- the event is not cancelled, duplicated, stale, or ambiguously timed;
- the logical instrument is mapped to this event family.

Actual, consensus, previous, and revision values may be journaled. They do not
directly choose long or short in version 1.

## Gate 2: Price acceptance

Direction is price-led:

- `LONG` candidate: mid price is above the pre-event high.
- `SHORT` candidate: mid price is below the pre-event low.

Acceptance passes only when the feature builder has identified the first valid
retest and the retest holds in the candidate direction. A complete return into
the pre-event range invalidates the setup.

Version 1 represents the retest result explicitly in `MarketSnapshot`. Phase 2
implements it as follows:

- use the first midpoint strictly outside the range after the 90-second shock
  window as breakout evidence;
- accept the first retest that remains outside and approaches the broken
  boundary to within one broker tick;
- require the following ordered primary tick to hold beyond that one-tick
  boundary;
- invalidate immediately if price enters the complete range, and classify a
  direct break of the opposite boundary as a whipsaw;
- use the opposite pre-event range boundary as the conservative initial stop.

Midpoints identify price structure only. Entries and exits always use the
executable bid or ask.

## Gate 3: Cross-asset confirmation

At least two observed related markets must vote for the same direction. Votes
are event-family-specific and must be documented. Examples are context, not
hard-coded promises:

- USD macro event: EURUSD, USDJPY, XAUUSD, and US index reactions.
- ECB event: EURUSD, GER40, and a USD reference.
- SNB event: USDCHF, EURCHF, and SMI when available.

The feature builder must record every observed vote and its timestamp. Missing
related markets do not count as neutral confirmations.

## Gate 4: Execution quality

Pass only when:

- current spread is no more than the configured multiple of baseline;
- all required market data is fresher than the maximum age;
- bid, ask, tick size, tick value, and volume constraints are valid;
- broker connection and account mode checks are healthy;
- a stop candidate exists on the loss side of entry;
- estimated quantity is within broker limits after rounding down.

## Candidate selection

When multiple instruments pass for the same event cluster, choose exactly one
using a deterministic ranking:

1. cleanest acceptance and retest validity;
2. lowest normalized spread;
3. strongest confirmation count;
4. stable logical-symbol tie breaker.

Do not open several versions of the same macro bet.

## Entry

- Entry uses the current executable side of the market or a documented stop/
  limit rule implemented by the broker adapter.
- The initial request includes the protective stop.
- The idempotency key is persisted before or atomically with submission.
- If the order cannot be sized exactly within the risk cap, reject it.
- If price runs away after the plan is calculated, do not chase beyond a
  configured maximum slippage.

## Exit

The MVP exit engine will implement:

- hard protective stop;
- invalidation when price accepts back inside the complete event range;
- partial realization around `+2R` only after replay validation;
- trailing remainder by documented swing/ATR rule;
- time exit at the configured session cutoff;
- emergency close through the kill switch.

Exit details are Phase 2 work and must be represented identically in replay and
demo. Moving a stop farther from entry is forbidden.

Phase 2 enables hard stop, complete range reclaim, emergency exit, and explicit
UTC session cutoff with that precedence. Long exits use bid and short exits use
ask. Partial realization near `+2R` and trailing remain disabled pending replay
validation and a versioned strategy decision; no unvalidated numeric rule is
silently introduced.

## Pyramiding

Pyramiding is post-MVP. If later approved, an addition is allowed only when the
new combined worst-case loss, including costs and slippage allowance, remains
at or below the original `1R`. No addition is ever allowed below the previous
entry in a long or above it in a short merely to improve average price.

## Immediate invalidation

- both sides of the pre-event range break during the setup window;
- the full range is reclaimed;
- spread or data-age gate fails;
- related markets reverse or become unavailable;
- event time or identity changes;
- another setup already consumed the event cluster;
- a risk lock activates.
