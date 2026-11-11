# Instruction Discovery Order

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Start points](#start-points)
- [Scope split](#scope-split)

## Start points

1. Repo root `AGENTS.md` for repo-wide constraints and preflight rules.
2. [../README.md](../README.md) for the front-door map of `codex/instructions/`.
3. For technical implementation or review, including changes to docs, config,
   release policy, testing, performance, security, or Git workflow, read
   [../CODESTYLE.md](../CODESTYLE.md) as the codestyle front door. A read-only
   status question needs it only when the answer depends on that contract.
4. [README.md](./README.md) as the governance-focused front door.
5. If one of the AGENTS files triggers a repo-local skill, open the matching file under ../../../.codex/skills/ (Configs dependency: `../../../.codex/skills/`).
6. Open only the task-specific references needed for the selected work. This map is for governance work, not a mandatory reading sequence for every technical edit; do not reread instruction files already loaded for the unchanged scope.

## Scope split

- Global defaults: `~/.codex/AGENTS.md` and linked `~/.codex/instructions/*`.
- Repo-level defaults: repo root `AGENTS.md` and `codex/instructions/*`.
- Coding standards pack: `codex/instructions/CODESTYLE.md` front door and `codex/instructions/codestyle/*` detail modules.
- Repo-local recurring workflows: `.codex/skills/*`.
- Governance subset: `codex/instructions/agents/*`.
- Living memory: `codex/FORJAMIE.md` (do not commit).
