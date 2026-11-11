# Chronicle Workflow

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Purpose](#purpose)
- [Memory Layers](#memory-layers)
- [Digest Command](#digest-command)
- [Review Rules](#review-rules)
- [Closeout Checklist](#closeout-checklist)

## Purpose

Chronicle is an observational memory surface. It records short windows of screen context and writes persisted summaries under:

`~/.codex/memories/extensions/chronicle/resources/`

The repo path `codex/memories_extensions/chronicle/resources/` is a legacy projection mirror. Use it only when intentionally reviewing archived repo-mirror content; do not treat it as the freshness source for Chronicle memory.

Use Chronicle to recover work state, validation evidence, blockers, and repeated workflow patterns. Do not treat Chronicle output as authoritative by itself; confirm important claims against repo files, command output, PR state, or explicit user direction.

## Memory Layers

- Chronicle: what was visible on screen.
- Project Brain files: reviewed repository context across sessions.
- Repo memory: accepted durable project rules, such as `.harness/memory/LEARNINGS.md`.
- Plan/spec: current intended work and acceptance criteria.
- Review log or handoff: decision and evidence trail for the current change.

Chronicle can propose durable learnings, but it does not decide them. Promote only repeated, actionable, and non-sensitive patterns into repo memory or instructions.

## Digest Command

Run the digest from the repository root:

```bash
bash codex/scripts/chronicle-digest.sh --limit 5
```

Use `--show-files` when you need the exact summaries inspected:

```bash
bash codex/scripts/chronicle-digest.sh --limit 5 --show-files
```

The digest groups recent summaries into active work signals, validation evidence, blockers, and candidate durable learnings. It is a triage aid, not a replacement for reading the source summaries when precision matters.

To inspect the legacy repo mirror instead of the live Chronicle store, pass the path explicitly:

```bash
bash codex/scripts/chronicle-digest.sh --resources-dir codex/memories_extensions/chronicle/resources --limit 5
```

## Review Rules

- Redact or avoid repeating private screen details unless they are needed for the task.
- Prefer exact failure strings and command names over broad paraphrase.
- Confirm blockers against live state before editing policy or scripts.
- Convert Chronicle observations into durable guidance only when the user has asked for workflow tightening or the same failure pattern has repeated.
- Prefer `~/.codex/memories/extensions/chronicle/resources/` for current Chronicle evidence.
- Treat `codex/memories_extensions/chronicle/resources/` as a legacy projection mirror, and keep hand-authored Chronicle guidance outside `resources/`.

## Closeout Checklist

Before ending a Chronicle-informed workflow, write down or report:

- Current task, branch, PR, and source-of-truth plan.
- Focused validation command and result.
- Broader validation command and result, or the concrete reason it was skipped or blocked.
- Known remaining blocker, with exact failure string when available.
- Durable learning accepted, rejected, or deferred.
- Heartbeat, automation, or follow-up action created, updated, deleted, or intentionally left alone.
