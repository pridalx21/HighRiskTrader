# Product brief

## Working title

CATALYST: Event Reaction Retest MVP

## Problem

Most retail trading bots fail for reasons that have little to do with coding:
they trade constantly, confuse a news headline with an edge, hide risk inside
leverage, and test a different implementation than the one eventually used.

CATALYST narrows the problem. It watches only known high-impact windows, waits
for the market to reveal its interpretation, requires confirmation from related
markets, and permits a trade only when the loss can be calculated before entry.

## Intended user

One private operator who wants a simple, understandable demo system and accepts
that a future speculative CHF 1,000 monthly risk capsule could be lost entirely.
The MVP is not multi-user software and does not manage third-party funds.

## Core promise

Every system state and every rejected or accepted setup can answer:

1. What event armed the system?
2. What price behavior established direction?
3. Which related markets confirmed it?
4. Which execution checks passed?
5. How much could be lost if the stop filled as planned?
6. Which exact rule ended the trade?

## Product principles

- **Reaction over prediction:** do not guess the release result.
- **No first-spike race:** wait through the worst spread and latency window.
- **Few binary gates:** avoid an opaque indicator soup.
- **Fail closed:** missing or ambiguous data means no trade.
- **One strategy first:** earn complexity with evidence.
- **Same core everywhere:** replay, demo, and any future live mode share logic.
- **Positive skew:** never rescue losers; later additions may amplify winners
  only when worst-case risk stays bounded.
- **Explainability is a feature:** every decision is journaled with rule codes.

## Success for the MVP

The MVP is successful when it can replay and demo-execute the same strategy,
reject unsafe conditions deterministically, produce a complete audit trail, and
survive disconnect/restart scenarios without accidental orders.

Profitability is a later empirical result, not an MVP acceptance criterion.

