# TypeScript Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Type discipline](#type-discipline)
- [Schema-owned domain types](#schema-owned-domain-types)
- [Banned patterns](#banned-patterns)
- [Linting and module rules](#linting-and-module-rules)
- [Async and cancellation](#async-and-cancellation)
- [Testing](#testing)
- [Enforcement](#enforcement)

## Scope

- This module is the canonical TypeScript-specific standards reference for this codestyle pack.

## Type discipline

- Explicit types at public API boundaries (functions, modules, component props) SHOULD be provided.
- Use strict TypeScript configuration and keep boundary validation explicit.
- `any` is discouraged in production paths; use concrete types or `unknown` plus narrowing.

## Schema-owned domain types

- Validate untrusted input before domain logic uses it. Preserve the owning
  schema, external identifier format and wire contract; derive types from an
  existing schema instead of manually duplicating its contract.
- Use branded identifiers or validating value types when they prevent a concrete
  mix-up or enforce a domain invariant. Ordinary primitives and typed records
  are appropriate when explicit constraints and units make their use clear.
- Validate ranges, finiteness and other required invariants at the boundary,
  regardless of the chosen representation. Static annotations and casts do not
  perform runtime validation. Do not add a dependency solely for a type-style rule.

## Banned patterns

- `: any`, `as any`, `Promise<any>`, and `Record<string, any>` are discouraged in production code.
- `value as unknown as T` double assertions SHOULD include runtime validation.
- `// @ts-ignore` and `// @ts-nocheck` SHOULD be avoided; use `@ts-expect-error` with rationale only when unavoidable.
- Unsafe type assertions SHOULD include guard functions or schema validation.

## Linting and module rules

- Use the repository-selected linter. If ESLint supplies semantic TS checks, configure it with type information; do not add it alongside a sufficient existing linter just for this reference.
- Biome handles formatting and style-level lint where configured and MUST pass where enabled.
- Prefer ESM and explicit module syntax for Node/TS packages.
- Keep imports acyclic; avoid barrels that create circular dependency chains.

## Async and cancellation

- Prefer `async/await` over nested Promise chains.
- Exported async APIs that do I/O or long work SHOULD accept `AbortSignal`.
- Surface cancellation as expected behavior, not as opaque failures.

## Testing

- Co-locate tests (`*.test.ts` / `__tests__`) and assert user-visible behavior where applicable.
- Keep snapshots limited to intentionally stable serialized outputs.
- Validate parsing boundaries (`JSON.parse`, `Response.json`) with schemas or typed helpers.

## Enforcement

- Use the shared Configs validation contract in [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Avoid soft bypasses for type/lint errors; temporary suppressions require a waiver with reason, tracker, and expiry/ADR.
- Validation evidence MUST be explicit:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
