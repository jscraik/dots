# Swift Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Language and API design](#language-and-api-design)
- [Domain value types](#domain-value-types)
- [Concurrency](#concurrency)
- [Error handling and state](#error-handling-and-state)
- [Testing and formatting](#testing-and-formatting)
- [Enforcement](#enforcement)

## Scope

- This module defines Swift coding standards for Apple-platform projects and utilities.

## Language and API design

- Prefer value semantics and protocol-oriented composition for shared logic.
- Keep API surfaces explicit and readable at call sites.
- Avoid hidden global state in core logic.

## Domain value types

- Validate untrusted input before domain logic uses it. Preserve the owning
  schema, external identifier format and wire contract; derive types from an
  existing schema instead of manually duplicating its contract.
- Use branded identifiers or validating value types when they prevent a concrete
  mix-up or enforce a domain invariant. Ordinary primitives and typed records
  are appropriate when explicit constraints and units make their use clear.
- Validate ranges, finiteness and other required invariants at the boundary,
  regardless of the chosen representation. Static annotations and casts do not
  perform runtime validation. Do not add a dependency solely for a type-style rule.

## Concurrency

- Prefer structured concurrency (`async/await`, task groups) over unmanaged thread patterns.
- Define actor or synchronization boundaries for mutable shared state.
- Keep UI-affecting updates on the appropriate main-thread or actor context.

## Error handling and state

- Propagate typed errors with actionable context.
- Avoid swallowing errors in async flows.
- Keep state transitions explicit and testable.

## Testing and formatting

- Keep unit tests deterministic and focused on behavior contracts.
- Separate heavier integration/UI tests from fast unit suites.
- Apply repo formatting/lint tooling consistently for Swift codepaths.

## Enforcement

- Use the shared Configs validation contract in [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Swift projects SHOULD also run native gates where available:
  - `swift test`
  - `xcodebuild test` (or project-defined equivalent)
- Concurrency and actor-boundary exceptions require explicit waiver metadata (reason, tracker, expiry/ADR).
