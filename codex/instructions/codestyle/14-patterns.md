# Common Patterns Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Core design principles](#core-design-principles)
- [Structural patterns](#structural-patterns)
- [Boundary and response patterns](#boundary-and-response-patterns)
- [Pattern-scope checks](#pattern-scope-checks)
- [Enforcement](#enforcement)

## Scope

- This module defines reusable implementation patterns that improve maintainability and consistency.

## Core design principles

- Prefer KISS, DRY, and YAGNI in that order.
- Favor immutable updates over in-place mutation in production paths.
- Keep functions focused and split deeply nested logic into named helpers.

## Structural patterns

- Organize by feature/domain boundaries instead of technology buckets when practical.
- Keep files cohesive; extract shared logic before copy-paste drift appears.
- Use repository/service abstractions when multiple storage backends or test doubles are required.

## Boundary and response patterns

- Validate all external input at boundaries before domain logic.
- Keep error structures and API envelopes consistent within a service surface.
- Use named constants for thresholds, limits, and policy values; avoid magic numbers.

## Pattern-scope checks

- A correction in one location MAY represent a reusable pattern defect. Before closeout, check for sibling abstractions, equivalent workflows, duplicated logic, unsafe defaults, stale variants, missing validators, and missing shared primitives.
- If a pattern defect is confirmed, prefer the smallest durable consistency mechanism: shared helper, schema check, validator, lint rule, CI gate, documented invariant, or tracked follow-up when immediate remediation would be too broad.
- If broader remediation is intentionally deferred, record the reason, expected owner or follow-up, and why the local fix remains safe.

## Enforcement

- Pattern changes SHOULD be reviewed with targeted examples in PR notes.
- Any deliberate deviation from these defaults MUST include rationale and a tracker reference.
