# Security and Governance

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Command-policy baseline](#command-policy-baseline)
- [Security defaults](#security-defaults)
- [Approval and review triggers](#approval-and-review-triggers)
- [Evidence requirements](#evidence-requirements)

## Scope

- Canonical instructions for security and change governance in this repo.
- Applies when tasks touch instruction docs, memory notes, or process automation.
- This is the policy doc for who can approve a governance-relevant change.

## Command-policy baseline

- `instructions/agents/02-tooling-policy.md` is the canonical source for repo-safe command use.
- Preferred discovery tools may use safe equivalents. A missing validator
  dependency blocks that validator, not independent work; report the distinction.

## Security defaults

- Do not store secrets, tokens, keys, or PII in repository docs or memory notes.
- `codex/FORJAMIE.md` remains internal-only and uncommitted, but must be kept current.
- If `AGENTS.md` or `codex/instructions/**` changes durable Jamie guidance, update `codex/FORJAMIE.md` on the same day before closeout.
- Validate path and command facts from repository content before documenting them.

## Approval and review triggers

- Follow the active AGENTS authority boundary. Continue already-authorized,
  bounded local corrections without a separate role ceremony.
- Changes that grant new authority or weaken a security boundary require the
  corresponding explicit authorization and risk-appropriate independent review.
- If an audit or release-control contract is explicitly selected, record its
  named participants, scope, and evidence through
  [09-audit-trail-policy.md](./09-audit-trail-policy.md).

## Evidence requirements

- Record commands and outputs used for verification, even when they are short.
- Cite all command outputs that failed or changed expected behavior.
- Keep durable policy references in their owning documents. Ordinary findings
  may be returned directly; only a selected artifact contract requires a report.
