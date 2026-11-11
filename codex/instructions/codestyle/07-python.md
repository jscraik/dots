# Python Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Runtime and environment](#runtime-and-environment)
- [Typing and API boundaries](#typing-and-api-boundaries)
- [Domain types and validation](#domain-types-and-validation)
- [Linting and formatting](#linting-and-formatting)
- [Testing](#testing)
- [Error handling and observability](#error-handling-and-observability)
- [Enforcement](#enforcement)

## Scope

- This module defines Python coding standards for repo scripts, utilities, and automation helpers.
- Follow these rules for `.py` files under repository control.

## Runtime and environment

- Use the Python version pinned by repo toolchain configuration.
- Keep Python invocations deterministic and scriptable (`python3 ...` from repo root when possible).
- Avoid user-specific paths and implicit global state in scripts.

## Typing and API boundaries

- Public functions and module entrypoints MUST have explicit type hints.
- Prefer concrete types and `typing` primitives over untyped dictionaries at boundaries.
- Validate external input payloads before use and narrow types early.

## Domain types and validation

- Validate untrusted input before domain logic uses it. Preserve the owning
  schema, external identifier format and wire contract; derive types from an
  existing schema instead of manually duplicating its contract.
- Use branded identifiers or validating value types when they prevent a concrete
  mix-up or enforce a domain invariant. Ordinary primitives and typed records
  are appropriate when explicit constraints and units make their use clear.
- Validate ranges, finiteness and other required invariants at the boundary,
  regardless of the chosen representation. Static annotations and casts do not
  perform runtime validation. Do not add a dependency solely for a type-style rule.
- Use standard-library types, dataclasses or the project's existing validation
  library as appropriate. Pydantic is an option where adopted, not a universal
  dependency. TypedDict and dataclass annotations alone do not validate input.

## Linting and formatting

- Ruff is the primary Python linter and MUST pass for changed Python paths.
- Keep style and import ordering consistent with repo lint configuration.
- Pyright MUST be used for static type checks where configured; failing type checks MUST block merge.
- Waivers or suppressions MUST include reason, tracking reference, and expiry when temporary.

## Testing

- Use the repository's maintained Python test runner; Configs includes unittest suites. Do not replace it solely to adopt pytest.
- Keep tests deterministic and avoid network or clock coupling unless explicitly mocked.
- Co-locate tests near Python modules when practical.

## Error handling and observability

- Do not swallow exceptions.
- Add actionable context to raised errors and logs.
- When scripts produce machine-consumed output, keep message structure stable.

## Enforcement

- Use the shared Configs validation contract in [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Python-focused checks MUST be run when relevant tooling is present in the touched project:
  - `ruff check <changed-python-paths>`
  - `pyright <changed-python-paths>`
  - the repository's affected-test command
- Validation records MUST include exact commands and outcomes:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
