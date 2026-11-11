# Code Review Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Mandatory review triggers](#mandatory-review-triggers)
- [Pre-review requirements](#pre-review-requirements)
- [Severity model](#severity-model)
- [Security review triggers](#security-review-triggers)
- [Approval criteria](#approval-criteria)
- [Enforcement](#enforcement)

## Scope

- This module defines review criteria and reviewer verdicts. A reviewer verdict
  is not merge permission; the applicable readiness receipt, independent review,
  zero unresolved threads and required checks remain separate gates under
  [Git and release governance](../agents/16-git-and-release.md).
- For Codex-specific diff checks, use the scoped
  [Code Review Rules](../../AGENTS.md#code-review-rules). Do not apply them to
  unrelated paths or turn mechanical CI checks into review findings.

## Mandatory review triggers

- Review is required for:
  - New features and bug fixes.
  - Security-sensitive surfaces.
  - Architectural or workflow-governance changes.
  - Any change that alters public behavior or release-critical scripts.

## Pre-review requirements

- Before requesting review:
  - Confirm branch is up-to-date with target base.
  - Resolve merge conflicts.
  - Run required validation gates and capture results.
  - For config/governance surfaces, include the configured required CI status and any required review-bot status in review evidence.

## Severity model

- `CRITICAL`: security/data-loss risk; merge blocker.
- `HIGH`: functional correctness risk; should be fixed before merge.
- `MEDIUM`: maintainability/design risk; fix when feasible in current scope.
- `LOW`: style or minor improvement; optional unless policy demands.

## Security review triggers

- Require dedicated security review when changes involve:
  - Authentication/authorization.
  - Secrets, credentials, tokens, or key management.
  - Input handling with execution/query implications.
  - Payment or sensitive data pathways.

## Approval criteria

- A reviewer may give a positive verdict when no CRITICAL/HIGH findings remain
  in that review's scope. Record any remaining findings and their disposition.
- An explicit risk acceptance with an owner documents a HIGH finding; it does
  not itself clear an unresolved thread or waive a readiness gate.
- Before claiming merge readiness, independently verify the receipt, required
  checks, review coverage and zero unresolved threads for the current PR head.

## Enforcement

- Review artifacts MUST reference concrete file paths and impacted behavior.
- Validation and review outcomes MUST be explicit and evidence-backed.
