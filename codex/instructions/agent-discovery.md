# Agent System Discovery Map

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


schema_version: 2

> Select this reference when investigating the local Codex control plane.
> This document is additive and intentionally Codex-only.

## Table of Contents

- [Preflight Gate](#preflight-gate)
- [Codex Overview](#codex-overview)
- [Skills](#skills)
- [Agents](#agents)
- [Rules And Instructions](#rules-and-instructions)
- [Profiles And Models](#profiles-and-models)
- [Hooks](#hooks)
- [Architecture Artifacts](#architecture-artifacts)
- [File System Reference](#file-system-reference)
- [Learnings Convention](#learnings-convention)

---

## Preflight Gate

Confirm the target repository and paths before acting. Use the narrowest check
that proves the task's boundary; [agents/04-validation.md](agents/04-validation.md)
defines when the broader Configs preflight and final checks apply. This reference
does not add a universal startup gate.

---

## Codex Overview

| Item | Value |
| --- | --- |
| CLI | `codex` |
| Home config root | `~/.codex/` |
| Canonical tracked root | `~/dev/configs/codex/` |
| Canonical instructions entrypoint | `~/.codex/AGENTS.md` |

Codex policy applies to Codex sessions. Other tools and repositories retain
their own local instruction and runtime contracts.

---

## Skills

Skills are reusable task modules invoked by name or auto-matched from context.

Primary Codex skill locations:

- `~/.codex/skills/`
- `~/dev/agent-skills/.agents/skills/` (workspace-scoped extensions)

Quick checks:

- `ls ~/.codex/skills/`
- `ls ~/dev/agent-skills/.agents/skills/`

---

## Agents

This repository retains optional coordinator deliverables:

| Path | Purpose |
| --- | --- |
| `~/dev/configs/codex/agents/` | Optional tracked review-contract templates |
| `~/.codex/agents/` | Metadata-only compatibility dir |

Guardrail:

- Keep `~/.codex/agents/` metadata-only. Named-role registration is retired by this repository's policy;
  do not add role TOMLs or a role manifest there.

---

## Rules And Instructions

Codex rules are stored in `~/.codex/rules/` and loaded every session.

Key files:

- `foundation.rules`
- `guard.rules`
- `pr.rules`
- `project.rules`
- `default.rules`

Codex instruction library root:

- `~/dev/configs/codex/instructions/`

---

## Profiles And Models

Configured in the tracked `~/dev/configs/codex/config.toml` policy source and
hydrated into the isolated runtime copy at `~/.codex/config.toml`.

| Key | Value |
| --- | --- |
| Runtime policy | Inspect `~/dev/configs/codex/config.toml` |
| Active profile | Inspect the current session or `codex --profile <name>` |

Runtime override:

- `codex --profile <name>`

---

## Hooks

Codex hook policy is driven by `~/.codex/hooks.json` projected from:

- `~/dev/configs/codex/hooks/hooks.json`

Validation commands:

- `bash codex/scripts/validate-codex-hooks.sh`
- `bash codex/scripts/audit-codex-symlinks.sh`

---

## Architecture Artifacts

Diagram outputs (when present):

```text
.diagram/
├── architecture.mmd
├── dependency.mmd
├── flow.mmd
├── security.mmd
├── context/
│   ├── diagram-context.md
│   └── diagram-context.meta.json
└── manifest.json
```

Use the target repository's installed diagram tool and documented command.
Do not fetch an unpinned package just to reproduce this illustrative layout.

---

## File System Reference

| Path | Purpose |
| --- | --- |
| `~/.codex/AGENTS.md` | Global Codex operator guidance |
| `~/dev/configs/codex/config.toml` | Canonical Codex runtime config |
| `~/.codex/config.toml` | Projected mutable runtime config copy; the canonical policy source remains in the repo |
| `~/.codex/skills/` | Codex skills |
| `~/.codex/rules/` | Codex rule files |
| `~/dev/configs/codex/agents/` | Optional tracked review-contract templates |
| `~/.codex/agents/` | Optional empty legacy directory; no role manifest or TOMLs are active in Desktop |
| `~/.codex/memories/MEMORY.md` | Durable cross-session memory |
| `~/dev/configs/codex/instructions/` | Shared Codex instruction library |
| `<repo-root>/.harness/memory/LEARNINGS.md` | Repo-specific append-only learnings |

---

## Learnings Convention

Use the repository-specific ledger:

- `<repo-root>/.harness/memory/LEARNINGS.md` for implementation and validation
  gotchas scoped to that repository.
- `codex/FORJAMIE.md` for this repository's uncommitted operator handoff.

Write format:

- `**YYYY-MM-DD [Codex]:** <problem> -> <fix>`

Rule: keep the selected ledger append-only and do not copy local runtime data,
credentials, or generated traces into it.
