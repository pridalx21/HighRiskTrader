# Execution plan template

Use this template for Phases 2–6 or any change spanning multiple components.
Copy it into the current Codex plan or a temporary task document; do not replace
`docs/PROJECT_STATUS.md` with it.

## Outcome

Describe the observable result, not merely the activity.

## Context

- Normative documents:
- Existing files/components:
- Input fixtures or external dependencies:
- Current project-status item:

## Constraints and non-goals

- Demo-only and risk invariants affected:
- Boundaries that must remain unchanged:
- Explicit non-goals:

## Assumptions and open questions

List only assumptions that could change implementation or acceptance. Resolve a
blocking question before coding.

## Implementation slices

Each slice should be testable end to end.

1. Slice:
   - Files:
   - Behavior:
   - Failure paths:
   - Tests:
2. Slice:
   - Files:
   - Behavior:
   - Failure paths:
   - Tests:

## Verification

- Baseline commands:
- Focused tests:
- Static checks:
- Manual/demo evidence:
- Replay evidence:

## Safety review

- Real/unknown account path:
- Initial protective stop:
- Stale/ambiguous data:
- Idempotency and restart:
- Float versus Decimal:
- Replay/demo divergence:
- Secret exposure:

## Documentation and decisions

- `PROJECT_STATUS.md` update:
- ADR needed:
- Operator/runbook changes:

## Completion record

- Commands actually run:
- Results:
- Remaining limitations:
- Next concrete task:

