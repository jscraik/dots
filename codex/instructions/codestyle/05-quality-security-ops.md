# Quality, Security, and Operations Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Detailed modules](#detailed-modules)
- [15. Quality Gates: Coverage, Mutation, TDD](#15-quality-gates-coverage-mutation-tdd)
- [16. Fast Tools (MANDATORY for agents)](#16-fast-tools-mandatory-for-agents)
- [17. Security, Supply Chain & Compliance](#17-security-supply-chain--compliance)
- [18. Accessibility](#18-accessibility)
- [19. Observability, Logging & Streaming](#19-observability-logging--streaming)
- [20. Resource Management & Memory Discipline](#20-resource-management--memory-discipline)
- [21. Repository Scripts & Reports](#21-repository-scripts--reports)
- [22. MCP & External Tools](#22-mcp--external-tools)
- [23. Config References (Authoritative)](#23-config-references-authoritative)

## Scope

- This module is a cross-cutting quality/security/operations umbrella.
- Topic-specific policy details are defined in dedicated modules listed below.

## Detailed modules

- Git workflow: [13-git-workflow.md](./13-git-workflow.md)
- Patterns: [14-patterns.md](./14-patterns.md)
- Performance: [15-performance.md](./15-performance.md)
- Security: [16-security.md](./16-security.md)
- Testing: [17-testing.md](./17-testing.md)
- Code review: [18-code-review.md](./18-code-review.md)
- Development workflow: [19-development-workflow.md](./19-development-workflow.md)
- Go: [20-go.md](./20-go.md)
- Artifact formats: [21-artifact-formats.md](./21-artifact-formats.md)

## 15. Quality Gates: Coverage, Mutation, TDD

PR merge gate MUST pass the repository contract commands:

- `pnpm lint` (parent repo root)
- `pnpm typecheck` (parent repo root)
- `pnpm test` (parent repo root)
- `bash scripts/verify-work.sh --fast` (codex subtree root) or `bash codex/scripts/verify-work.sh --fast` (parent repo root)

Coverage and mutation thresholds MAY be enforced only when wired to executable repository validators.

---

## 16. Fast Tools (MANDATORY for agents)

- Use `rg` not `grep` for project-wide search.
- Prefer `fd` for file finding.
- Use `jq` for JSON parsing/transformations.
- Read limits: cap reads at ~250 lines; prefer targeted context flags.

---

## 17. Security, Supply Chain & Compliance

- No hard-coded secrets; use env injection/secret manager.
- Validate/sanitize all external inputs.
- Scanning per PR SHOULD include:

  - OSV / audits per ecosystem
  - Semgrep policy + OWASP
  - SBOM generation at release (CycloneDX)
  - provenance/signing (SLSA/in-toto + Sigstore) where applicable
- Containers (if used): minimal base, non-root, read-only FS, drop caps.

---

## 18. Accessibility

- Baseline: WCAG 2.2 AA.
- Full keyboard operation required.
- Screen reader compatibility required.
- CLI/TUI: `--plain` / `--no-color` modes required.

---

## 19. Observability, Logging & Streaming

- OpenTelemetry SHOULD be used where services/CLIs exist.
- Logs SHOULD be structured and include `service` at app boundaries.
- Streaming:

  - default token delta streaming for CLIs,
  - optional aggregated mode,
  - JSON event streaming optional if supported.

---

## 20. Resource Management & Memory Discipline

- Respect repo-defined concurrency limits for pnpm/CI tasks.
- Measure before increasing parallelism; attach before/after results to PR when changing.

---

## 21. Repository Scripts & Reports

- If codemap/report tooling exists, outputs MUST include service identity and be attachable to PRs.

---

## 22. MCP & External Tools

- Adapters/helpers MUST not hard-code user-specific paths.
- Health checks MUST be scriptable.
- Egress/network policies MUST be explicit where required.

---

## 23. Config References (Authoritative)

- Package contract: `package.json`, `pnpm-lock.yaml`, and `Makefile`
- JS/formatting: `biome.json`; ESLint config only when present in a touched project
- Docs: `.markdownlint.yaml`; `.vale.ini` only when present
- Python: `ruff` and `pyright` only where configured for the touched project
- Rust: `rustfmt.toml`, `Cargo.toml`, and Clippy only where configured for the touched project
- Mise/tooling: `.mise.toml` for repository pins; `mise/config.toml` for the
  separate workstation-wide configuration
- Codex runtime: `codex/config.toml`, `codex/projection-map.json`, `codex/requirements.toml`
- Hooks and projection: `codex/hooks/**`, `codex/scripts/install-codex-hooks.sh`, `codex/scripts/audit-codex-symlinks.sh`
- CI/policy: `.circleci/config.yml`, `.github/workflows/**`, `harness.contract.json`

---
