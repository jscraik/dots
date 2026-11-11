# Independent Review Governance

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [When this applies](#when-this-applies)
- [Boundaries](#boundaries)
- [Review return](#review-return)

## When this applies

Use an independent reviewer only when Jamie requests a review, a repository
contract requires it, or one reviewer cannot cover a material risk surface.
Direct Work does not require proposer, reviewer, and approver roles.

## Boundaries

- Give every reviewer a candidate, base, bounded files or behavior, and a
  concrete question.
- A reviewer may inspect and report. The owning task retains implementation,
  validation, and hosted-state authority unless its selected contract says
  otherwise.
- Do not require an artifact, role registry, or session-collector output unless
  the selected review contract explicitly names it.
- Missing hosted evidence blocks only the hosted claim it would prove; it does
  not block local diagnosis or a focused patch.

## Review return

Return one compact candidate-bound result containing the reviewer identity,
candidate and base, verdict, severity-ranked findings, command evidence, and
claims boundary. If blocked, return the blocker class, exact failure, fallback
attempted, and next action. The coordinator verifies the return before relying
on it.
