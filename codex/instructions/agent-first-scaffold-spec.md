# Agent-First Scaffold Spec

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Purpose](#purpose)
- [Required marker blocks](#required-marker-blocks)
- [Plan contract](#plan-contract)
- [Validation commands](#validation-commands)
- [Rollout policy](#rollout-policy)

## Purpose

This is an explicitly selected scaffold convention, not a prerequisite for
ordinary edits. Preserve existing repository structure unless this route is requested.

## Required marker blocks

Use these exact markers and keep content inside them idempotent:

- `AGENTS.md`: `<!-- AGENT-FIRST-SCAFFOLD:START --> ... <!-- AGENT-FIRST-SCAFFOLD:END -->`
- `.agent/PLANS.md`: `<!-- AGENT-FIRST-PLANS:START --> ... <!-- AGENT-FIRST-PLANS:END -->`
- `README.md`: `<!-- AGENT-FIRST-WORKFLOW:START --> ... <!-- AGENT-FIRST-WORKFLOW:END -->`

Rules:

- Insert missing blocks; do not duplicate existing blocks.
- Merge scoped updates inside blocks; preserve non-block content.
- Avoid destructive overwrites.

## Plan contract

`.agent/PLANS.md` must model tasks as a DAG:

- top-level `tasks[]`
- each task includes a nonempty `id` and a `depends_on` list
- descriptive titles are useful but not enforced by this validator
- IDs must be unique
- `depends_on` must reference in-plan IDs only
- no self-dependency
- graph must be acyclic; independent components are permitted

## Validation commands

- `python3 ${CODEX_POLICY_SOURCE}/scripts/plan-graph-lint.py <plan-file>`
- `bash ${CODEX_POLICY_SOURCE}/scripts/verify-work.sh`

## Rollout policy

The following are illustrative rollout levels, not implemented switches in
`plan-graph-lint.py`. That CLI reports validation success or failure. A consuming
repository must implement a level before claiming it is enforced:

1. `warn`: non-blocking visibility
2. `block`: required remediation before merge
3. `strict`: blocked plus explicit governance evidence
