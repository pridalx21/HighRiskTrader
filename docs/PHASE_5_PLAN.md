# Phase 5 implementation plan

## Outcome

CATALYST exposes a one-page, read-only operator view and a narrow authenticated
control plane for `ARM AUTO-DEMO`, `DISARM`, `KILL SWITCH`, and incident
acknowledgement. The dashboard cannot create or modify numeric trade parameters.

## Implemented boundary

- `catalyst.dashboard.DashboardSnapshot` is an immutable presentation model for
  event, state, four gates, plan, account/risk, orders, positions, recent
  decisions, and replay export.
- `catalyst.controls.OperatorControlPlane` accepts only typed commands. It
  requires local token authentication and explicit confirmation.
- Arming requires fresh dashboard state, a healthy journal, a clear kill-switch
  latch, and successful broker-side demo arming.
- Every accepted arm/disarm/incident action is journaled. Arming is rolled back
  if the control audit cannot be persisted.
- `LocalKillSwitch` is a persistent local latch. It is engaged before attempting
  broker or journal calls and therefore remains effective during dependency
  failures.
- `GuardedDemoBroker` enforces the same latch directly in the order path.
- `catalyst-kill-switch` is a standalone safety-only command that can engage,
  but never clear, the latch.

## Non-goals

- No entry, stop, direction, volume, leverage, or risk input exists in the UI.
- The dashboard does not call strategy or risk calculation code.
- No remote dashboard is part of the MVP.
- A dashboard process failure cannot clear a latch or arm the broker.

## Acceptance

- stale/future dashboard state cannot arm;
- authentication and confirmation are required;
- kill-switch tests pass with broker/journal dependency failure;
- the broker guard blocks submission while the persistent latch exists;
- incident clear requires execution disarmed and a healthy audit journal;
- dashboard snapshots are immutable and contain at most the four deterministic
  strategy gates.
