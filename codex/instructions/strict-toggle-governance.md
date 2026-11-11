# Strict Toggle Governance

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Purpose](#purpose)
- [Toggle levels](#toggle-levels)
- [Gate behavior](#gate-behavior)
- [Required reporting](#required-reporting)

## Purpose

Illustrative design vocabulary for repositories that explicitly implement these
levels. This document does not enable a runtime toggle or a new approval gate.

## Toggle levels

- `warn`: report violations, allow progress.
- `block`: block progress on violations.
- `strict`: block progress and require explicit remediation evidence.

There is no default toggle imposed here. Inspect the consuming repository's
executable contract before using these labels.

## Gate behavior

- Apply the highest active toggle to each gate.
- Never downgrade from `block` or `strict` without explicit approval.
- Resolve conflicting declarations against the executable source of truth; ask only when a material policy choice remains.

## Required reporting

For each run, include:

- active toggle level
- gates evaluated
- blocked vs warned outcomes
- unresolved blockers
