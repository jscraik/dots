# Agent Governance Doc Set

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Use this index when a task changes repo governance, approval flow, testing gates, release controls, or audit evidence.

## Table of Contents

- [Read order](#read-order)
- [Open this set when](#open-this-set-when)
- [Core governance docs](#core-governance-docs)
- [Specialized runbooks](#specialized-runbooks)
- [Direct-work and review governance](#direct-work-and-review-governance)
- [Resolved local defaults](#resolved-local-defaults)

## Read order

1. Repo root `AGENTS.md`
2. [../README.md](../README.md)
3. [01-instruction-map.md](./01-instruction-map.md) for scope split and discovery order
4. The specific governance doc for the task

## Open this set when

- the task changes repo governance, approval flow, testing gates, release controls, or audit evidence
- the task edits `AGENTS.md` or `instructions/agents/**`
- the task changes role boundaries, release checks, audit trail policy, or governance validation

## Core governance docs

- [05-contradictions-and-cleanup.md](./05-contradictions-and-cleanup.md)
- [06-security-and-governance.md](./06-security-and-governance.md)
- [07a-role-governance.md](./07a-role-governance.md)
- [07b-agent-governance.md](./07b-agent-governance.md)
- [08-release-and-change-control.md](./08-release-and-change-control.md)
- [09-audit-trail-policy.md](./09-audit-trail-policy.md)
- [10-agent-testing-gates.md](./10-agent-testing-gates.md)

## Specialized runbooks

- [15-parallel-sessions.md](./15-parallel-sessions.md)
- [16-git-and-release.md](./16-git-and-release.md)
- [16a-review-reply-parsing.md](./16a-review-reply-parsing.md) only for
  authenticated CodeRabbit chat-reply evaluation during PR readiness
- [17-external-integrations.md](./17-external-integrations.md)
- [18-codex-platform-readiness.md](./18-codex-platform-readiness.md)

## Direct-work and review governance

Direct Work is the normal path. A named bounded outcome authorizes reversible
local implementation and focused validation; it does not require a role
ceremony, per-step approval, or artifact fan-out.

Use [07a-role-governance.md](./07a-role-governance.md) and
[07b-agent-governance.md](./07b-agent-governance.md) only when a task has an
explicit multi-agent or independent-review requirement. A selected artifact
contract is exceptional and must identify its owning writer and validator.

The optional artifact controls are in
[07b-agent-governance.md](./07b-agent-governance.md). Select only those required
by the repository's named deliverable; ordinary completion needs no artifact.

## Resolved local defaults

- Single-threaded communication wins in this repository.
  - Keep the human-facing interaction low-branching and easy to follow.
- Internal execution may use bounded parallelism only when Jamie explicitly
  requests it or an independent-review requirement makes it necessary.
- `codex/FORJAMIE.md` remains required as uncommitted living memory when the repo workflow asks for it.
- If a task changes durable Jamie guidance in `AGENTS.md` or `codex/instructions/**`, update `codex/FORJAMIE.md` before closeout and mention the changed files.
