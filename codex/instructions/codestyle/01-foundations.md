# Foundations and Baseline Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [0. Gold Production Standards (Hard Prohibitions)](#0-gold-production-standards-hard-prohibitions)
- [Domain primitives and schema ownership](#domain-primitives-and-schema-ownership)
- [1. General Principles](#1-general-principles)
- [2. Task Orchestration (Repo-Defined)](#2-task-orchestration-repo-defined)
- [3. Node.js Standards](#3-nodejs-standards)

## 0. Gold Production Standards (Hard Prohibitions)

**ABSOLUTE PROHIBITION** — It is a policy violation to ship or describe anything as “production-ready”, “complete”, “operational”, or “fully implemented” if any of the following exist anywhere in a **production code path**:

- Fabricated data/entropy: `Math.random()` (or equivalent) used to fabricate data without injected seed
- Hard-coded mock responses in production paths
- `TODO`/`FIXME`/`HACK` comments in production paths
- Placeholder stubs (“will be wired later”, “not implemented”, etc.)
- Disabled features signaling gaps (`console.warn("not implemented")`, dead flags)
- Fake metrics or synthetic telemetry presented as real

**Production code path** = any code that:

- ships in release artifacts,
- executes in deployed services/CLIs/apps,
- is reachable in release builds (even behind runtime flags).

### Identity and Truthfulness

- Apps/binaries/services MUST include **service identity** in outputs, error messages, and logs (`service:"<service_name>"`).
- Shared libraries SHOULD avoid hard-coded identity; prefer injected structured fields.
- Status claims in UIs/logs/docs MUST be evidence-backed by code and passing checks.

### Detection

- Pattern guards/AST-Grep/Semgrep/CI checks fail on violations.
- Exceptions require an ADR and a time-boxed waiver (see Appendix B).

---

## Domain primitives and schema ownership

- Validate untrusted input before domain logic uses it. Preserve the owning
  schema, external identifier format and wire contract; derive types from an
  existing schema instead of manually duplicating its contract.
- Use branded identifiers or validating value types when they prevent a concrete
  mix-up or enforce a domain invariant. Ordinary primitives and typed records
  are appropriate when explicit constraints and units make their use clear.
- Validate ranges, finiteness and other required invariants at the boundary,
  regardless of the chosen representation. Static annotations and casts do not
  perform runtime validation. Do not add a dependency solely for a type-style rule.

## 1. General Principles

- **Functional-first**: prefer pure, composable functions.
- **Classes**: only when required by a framework or to encapsulate unavoidable state.
- **Functions**: SHOULD be <= 40 LOC; split if readability suffers.
- **Exports**: named exports only; no `export default`.
  - Exception: framework conventions that require default exports (e.g., certain Next.js special files).
- **Determinism**: no ambient randomness/time in core logic; inject seeds/clocks/IDs.
- **Errors**: never swallow errors; add context and route to logging layer.
- **Cancellation**: long-running work MUST accept cancellation (AbortSignal in JS/TS; cancellation tokens/channels in Rust).

---

## 2. Task Orchestration (Repo-Defined)

- Use the repo’s task runner and “smart” wrappers when provided.
- If the repo uses an affected-only execution strategy, apply it where possible.
- Heavy targets SHOULD be serialized where the repo defines resource discipline.

---

## 3. Node.js Standards

- Packages MUST target the repo baseline Node version (pinned).
- JS/TS packages MUST use ESM (`"type": "module"`); avoid CJS unless a pack explicitly permits it.
- Prefer Node standard capabilities where appropriate (test runner for small libs is allowed).
- JSON imports MUST use import attributes where runtime requires it:

  ```ts
  import data from "./foo.json" with { type: "json" };
  ```

---
