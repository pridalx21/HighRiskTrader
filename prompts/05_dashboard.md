# Prompt 05: Build the operator dashboard

## Goal

Build a one-page local dashboard that makes every state and decision easy to
understand while preserving a narrow, safe control boundary.

## Required views

- next event and affected logical markets;
- current state: sleeping, armed, shock, waiting, ready, position, expired,
  locked, or disarmed;
- four strategy gates with reason codes and evidence;
- proposed entry, stop, volume, and maximum planned CHF loss;
- current account, day P&L in CHF and R, open risk, and active locks;
- orders, positions, and recent decision journal;
- replay inspection and report download.

## Controls

- explicit auto-demo arm/disarm;
- kill switch;
- acknowledge/review incident;
- no free-form numeric trade fields.

## Constraints

- Dashboard is not the trading core.
- It may request only typed control commands through a narrow port.
- It cannot generate or modify direction, entry, stop, volume, or risk.
- Kill switch must also be callable without the dashboard.
- No LLM dependency.

## Done when

- a non-technical user can explain why a trade did or did not happen;
- stale dashboard data is visibly marked and cannot arm execution;
- control actions are authenticated locally, confirmed, and journaled;
- UI failure does not change core safety state;
- automated UI/state tests cover the critical flow;
- baseline, docs, and project status are current.

