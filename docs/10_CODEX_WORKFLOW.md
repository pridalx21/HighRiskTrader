# Codex workflow

## Why this repository uses AGENTS.md

Codex reads repository guidance from `AGENTS.md` before work. This project keeps
the root file concise enough to define durable commands, architecture rules,
safety boundaries, and completion criteria while the detailed domain contracts
remain in `docs/`.

Official references:

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex best practices](https://learn.chatgpt.com/guides/best-practices)
- [Long-running work](https://learn.chatgpt.com/docs/long-running-work)
- [Prompting](https://learn.chatgpt.com/docs/prompting)

## One chat per outcome

Use a new Codex chat for each numbered phase. Continue the same chat for tests,
bug fixes, and review that belong to that phase. Start another chat only when
the outcome changes materially.

## Prompt structure

Every phase prompt includes:

- **Goal:** observable outcome;
- **Context:** exact files and current phase;
- **Constraints:** safety and architectural boundaries;
- **Done when:** commands and evidence that prove completion.

Do not replace a precise phase prompt with “build the bot.”

## Recommended first command

```text
Summarize the current repository instructions, normative documents, project
status, and baseline verification commands. Do not edit anything yet.
```

This detects whether Codex opened the correct repository root.

## Planning

Ask for a plan before phases 2–6. The plan should identify:

- files to change;
- data contracts affected;
- tests to add;
- failure modes;
- documentation or ADR updates;
- explicit non-goals.

Reject plans that introduce live execution, hidden dependencies, or a parallel
strategy implementation.

## Review loop

At the end of a phase ask:

```text
Review the complete diff against AGENTS.md, docs/04_RISK_POLICY.md, and the phase
acceptance criteria. Look specifically for fail-open behavior, real-account
paths, float money arithmetic, divergent replay/demo logic, nondeterministic
tests, and undocumented parameter changes. Fix verified issues, rerun checks,
and update PROJECT_STATUS.md.
```

## Context maintenance

- Keep `docs/PROJECT_STATUS.md` current; it is the handoff between chats.
- Put durable decisions in `docs/08_DECISION_LOG.md`, not only in chat.
- Put repeatable verification in scripts, not only in prose.
- When Codex repeats the same mistake, improve `AGENTS.md` with one concise rule.
- Do not grow `AGENTS.md` into a second architecture document.

## Parallel work

Avoid two agents editing the same checkout. If parallel work is explicitly
chosen later, use separate Git worktrees and assign bounded, non-overlapping
subtasks such as fixtures versus dashboard design. Merge only after both sides
pass the full baseline.

