# Security Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Mandatory checks](#mandatory-checks)
- [Secret handling](#secret-handling)
- [Secure coding defaults](#secure-coding-defaults)
- [Incident response workflow](#incident-response-workflow)
- [Enforcement](#enforcement)

## Scope

- This module defines security expectations for code, configuration, and release surfaces.

## Mandatory checks

- Before commit/PR handoff, verify:
  - No hardcoded secrets or credentials.
  - Input validation exists at trust boundaries.
  - Auth/authz logic changes are explicitly reviewed.
  - Error outputs do not leak sensitive data.
  - Semgrep static analysis scans passed on PRs and CI.
  - Policy-guard (or equivalent policy-as-code) checks passed.
  - Supply-chain scanning (SCA/Dependency review) completed for PRs and CI.

## Secret handling

- Secrets MUST come from environment injection or a secret manager.
- Exposed secrets MUST be rotated immediately and treated as incidents.
- Do not print raw secret values in logs, test fixtures, or screenshots.
- Record security tooling configuration (Semgrep rulesets, policy repo, SCA tool versions) in the security checklist or tooling manifest.

## Secure coding defaults

- Use parameterized queries for data access.
- Sanitize untrusted content before rendering/execution.
- Apply least-privilege defaults for runtime permissions and network access.
- For untrusted paths, destructive operations, or consequential publication,
  validate path type and containment, reject traversal and symlink escapes,
  and bind concurrent replacement to the validated target. Routine
  trusted-source reads need only relevant path checks.

## Incident response workflow

1. Stop work on unrelated changes.
2. Classify severity and blast radius.
3. Fix CRITICAL vulnerabilities before proceeding with normal work.
4. Add regression checks that prevent reintroduction.

## Enforcement

- Security findings at CRITICAL severity are merge blockers.
- Exceptions MUST include waiver metadata with rule ID or section, reason, tracking ticket, and either an expiry date or ADR reference.
