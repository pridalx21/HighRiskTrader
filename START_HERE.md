# Start CATALYST with Codex

## Five-minute start

1. Create a new Git repository from this folder.
2. Open the repository root in Codex.
3. Send this first message:

```text
Read AGENTS.md and docs/PROJECT_STATUS.md. Summarize the non-negotiable
demo-only and risk invariants, inspect the repository, then run the baseline
verification. Do not change code yet. Report any discrepancy between docs,
tests, and implementation.
```

4. If the baseline is clean, paste the contents of `prompts/00_kickoff.md`.
5. Continue with one numbered prompt per coherent Codex chat.

## Working rhythm

- Use one chat for one phase or one coherent bug.
- Ask Codex to plan before broad changes.
- Let Codex implement and verify, then review the diff.
- Never accept a change that weakens demo-only checks or risk gates.
- Update `docs/PROJECT_STATUS.md` at the end of every phase.
- Create a Git commit only after verification passes.

## What not to configure yet

Do not add OpenClaw, n8n, a VPS, Docker, a real broker login, paid news feeds,
machine learning, or a database server during the domain and replay phases.
Those tools cannot create a trading edge and would hide unfinished core logic.

