# Foundations and Baseline Standards

These portable principles are scoped by the [CODESTYLE front door](../CODESTYLE.md).
The active repository's supported interfaces and executable contracts take precedence
over a generic implementation preference.

## Table of Contents

- [0. Gold Production Standards (Hard Prohibitions)](#0-gold-production-standards-hard-prohibitions)
- [Domain primitives and schema ownership](#domain-primitives-and-schema-ownership)
- [1. General Principles](#1-general-principles)
- [2. Task Orchestration (Repo-Defined)](#2-task-orchestration-repo-defined)
- [3. Node.js Standards](#3-nodejs-standards)

## 0. Gold Production Standards (Hard Prohibitions)

Do not present fabricated data, synthetic telemetry, unimplemented required
behaviour or unverified delivery as real or complete. Release acceptance concerns
the promised behaviour and supported production paths.

A TODO comment, staged feature flag or intentionally disabled integration is not
automatically a release blocker. Assess whether it prevents an acceptance criterion,
exposes a security problem or misrepresents capability. Record genuine limitations.

Use deterministic clocks, IDs and randomness where reproducibility matters.
Use appropriate system randomness for security-sensitive values; never replace it
with a seeded test generator in production. Inject substitutes in tests.

### Identity and Truthfulness

Use the application's existing logging and error conventions. Include service or
operation identity where it helps consumers distinguish sources; do not force a
JSON service field into every CLI, human error message or library.

### Detection

Use configured linters and behavioural checks for objective invariants.
Do not claim a pattern guard enforces a rule until its maintained entrypoint is
verified. Qualitative decisions require review, not a keyword ban.

## Domain primitives and schema ownership

Validate untrusted input at its owning boundary. Preserve wire formats and schema
ownership. Use a branded identifier or validating value type for a concrete invariant
or mix-up risk; ordinary primitives and typed records are appropriate otherwise.
Annotations alone do not validate runtime data. Do not add a dependency just for style.

## 1. General Principles

- Keep responsibilities cohesive and side effects explicit.
- Prefer simple functions; use classes when they improve a real domain model,
  lifecycle or state boundary.
- Split functions when doing so improves understanding or independent testing,
  not to meet an arbitrary line count.
- Follow the package's established exports and framework conventions.
- Preserve errors with useful context; handle expected absence explicitly.
- Bound long-running operations and support cancellation where callers need it.
- Change shared mechanisms only after checking their actual consumers.

## 2. Task Orchestration (Repo-Defined)

Use the repository's maintained task runner. Apply affected-test selection where
the repository supports it and retain required broader checks. Follow measured
resource constraints; no generic role ceremony or extra orchestration framework
is needed for a small local change.

## 3. Node.js Standards

Use the repository's runtime, module format and package-manager lock. Prefer ESM
for new packages when supported; do not migrate working CommonJS merely to satisfy
portable guidance. Use runtime-supported JSON import syntax. Built-in test runners
are suitable where they meet the project's needs.
