# Development Workflow Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Contract and execution boundaries](#contract-and-execution-boundaries)
- [Research and reuse first](#research-and-reuse-first)
- [Systemic correction pass](#systemic-correction-pass)
- [Plan before implementation](#plan-before-implementation)
- [Build and verify loop](#build-and-verify-loop)
- [Pre-review readiness](#pre-review-readiness)
- [Enforcement](#enforcement)

## Scope

- This module defines the end-to-end feature workflow before and around Git/PR operations.
- It complements [13-git-workflow.md](./13-git-workflow.md), which covers commit and PR mechanics.

## Contract and execution boundaries

- Parse structured inputs with the appropriate parser. Validate required
  fields, types, allowed values, and relationships before use; substring
  matches, truthiness, and permissive coercion do not prove a contract.
- When changing a contract, update its affected producers and consumers,
  and any applicable schemas, generated artifacts, and operator guidance
  together. Regenerate affected derived files with the repository command
  and verify agreement before closeout.
- Preserve command exit status and distinguish failure, unavailability, and
  success. Do not consume partial output as successful data after failure.
  Bound external calls and subprocesses with timeouts; clean up owned child
  processes and resources on failure.
- Validate replacement output before changing the last good state. Make
  publication and rollback safe against partial failure and concurrent changes,
  retain recoverable backups, and release only resources owned by the current
  operation.

## Research and reuse first

- Before writing new implementation code, search the current repository for an
  existing pattern. Reuse or adapt proven patterns where practical.
- A well-understood local change may proceed from sufficient repository contracts
  and tests without an unrelated upstream search.
- Verify trusted upstream sources (official docs, library docs or primary
  references) when an external or version-sensitive contract, unfamiliar
  technique, unresolved uncertainty or consequential claim needs evidence.
  Match version-sensitive evidence to the version in use.
- If required evidence is unavailable within authorised access, record the gap
  and stop the dependent change or claim. Continue independent local work.

## Systemic correction pass

When a correction reveals a transferable failure pattern, check the relevant
sibling implementations. Keep the investigation bounded by the demonstrated
pattern rather than requiring a classification ceremony before a local fix.

The pass MUST stay proportional and evidence-led:

1. Identify sibling implementations, duplicated patterns, equivalent workflows, shared abstractions, validators, schemas, and CI gates that could carry the same failure mode.
2. Estimate blast radius and confidence from repo evidence, not speculation.
3. Choose the narrowest durable remediation class that fits the evidence: local fix, subsystem alignment, repository-wide alignment, validator or lint rule, schema enforcement, shared primitive, recovery handler, CI enforcement, policy update, or workflow redesign.
4. Explain why broader remediation is or is not justified when closing out the work.

Agents MUST NOT silently expand into broad rewrites. If the evidence supports only a local fix, record that scope decision. If fixing only one instance would leave the repository inconsistent, add or propose the smallest enforcement or follow-up that prevents recurrence.

## Plan before implementation

- For multi-step work, define a short implementation plan before editing.
- Identify risks, dependencies, validation gates, and rollback path up front.
- Keep scope explicit; defer non-required follow-ups rather than blending unrelated work.

## Build and verify loop

1. Implement the smallest meaningful increment.
2. Run relevant tests/validators immediately.
3. Fix failures before expanding scope.
4. Repeat until the intended behavior and contract checks are green (or explicitly blocked).

## Pre-review readiness

- Before handoff or PR review:
  - Ensure branch state and diff scope are understood.
  - Ensure required validation commands were run and recorded.
  - Ensure blocker reasons are explicit for any skipped or blocked checks.

## Enforcement

- Use the active repository contract routed by [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Use exact command evidence format:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
