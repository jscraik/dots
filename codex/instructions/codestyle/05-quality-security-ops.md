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

PR merge gates use the active repository's executable contract. Select commands
from the [CODESTYLE front door](../CODESTYLE.md#command-scope), not a package
manager assumed by this shared library. Passing local checks does not establish
hosted CI, independent review or merge readiness.

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

- Reports identify the project and evidence needed by their consumer. Add service
  identity only when it disambiguates multiple services. Keep private runtime
  data out of public reports.

---

## 22. MCP & External Tools

- Adapters/helpers MUST not hard-code user-specific paths.
- Health checks MUST be scriptable.
- Egress/network policies MUST be explicit where required.

---

## 23. Config References (Authoritative)

- Package contract: the active repository's manifest, lockfile and command wrapper
- JS/formatting: `biome.json`; ESLint config only when present in a touched project
- Docs: `.markdownlint.yaml`; `.vale.ini` only when present
- Python: `ruff` and `pyright` only where configured for the touched project
- Rust: `rustfmt.toml`, `Cargo.toml`, and Clippy only where configured for the touched project
- Mise/tooling: `.mise.toml` for repository pins; `mise/config.toml` for the
  separate workstation-wide configuration
- Codex runtime: `codex/config.toml`, `codex/projection-map.json`, `codex/requirements.toml`
- Hooks and projection: `codex/hooks/**`, `codex/scripts/install-codex-hooks.sh`, `codex/scripts/audit-codex-symlinks.sh`
- CI/policy: `.circleci/config.yml`, `.github/workflows/**`, `harness.contract.json`

Only existing, adopted configuration is authoritative for a project.

### Private self-hosted CI

Private projects may use GitHub Actions or CircleCI on the designated private
runner host. Select one required CI workflow per project; do not require both
providers merely because both runners are installed. Keep the host name,
registration credentials and machine inventory in private operational records.

Separate runner service identities and job workspaces. Limit repository access,
tokens, concurrency and job timeouts. Keep deployment credentials out of ordinary
test jobs. Use disposable job environments where feasible; a separate Unix user
or working directory alone does not prove isolation from hostile code.

Run only authorised private workloads on persistent runners. Evaluate external
contributions separately before they can execute on the host or access secrets.
For GitHub Actions, select an explicit runner group/labels and least-privilege
job token permissions. For CircleCI, use the registered resource class and its
supported machine/container executor; a hosted `resource_class: small` job does
not automatically move to an SSH-accessible machine.

Use the same repository validation entrypoint locally and in CI. Pin workflow
dependencies through the provider's supported immutable dependency mechanism.
Keep Linux CLI proof separate from macOS Desktop proof. Before declaring a
runner ready, verify a disposable job, cleanup, permissions and required-check
reporting; an active service or an SSH connection proves only that observation.

Provider references: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use)
and [CircleCI self-hosted runners](https://circleci.com/docs/runner-overview/).

---
