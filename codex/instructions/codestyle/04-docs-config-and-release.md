# Docs, Config, and Release Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [10. Documentation & Prose (Vale)](#10-documentation--prose-vale)
- [11. Data & Config Formats (YAML / TOML / JSON)](#11-data--config-formats-yaml--toml--json)
- [11a. Artifact and non-code formats](#11a-artifact-and-non-code-formats)
- [12. Naming Conventions](#12-naming-conventions)
- [13. Commits, Releases, ADRs](#13-commits-releases-adrs)
- [14. Toolchain & Lockfiles](#14-toolchain--lockfiles)

## 10. Documentation & Prose (Vale)

Maintained docs and long-form prose MUST be linted with Vale and MUST fail CI on Vale errors.
The parent repo currently runs broad Markdown linting through `pnpm docs:lint`; `docs:style:changed` MUST run Vale for staged scoped prose files.
Maintained prose files matching `**/*.{md,mdx,adoc,rst}` MUST be covered by the repository's Vale configuration.
Large generated resource directories, including `codex/memories_extensions/chronicle/resources/**`, are governed by the artifact-format rules in [21-artifact-formats.md](./21-artifact-formats.md) and dedicated validators instead of broad Vale prose linting.

### Scope

- `**/*.md`, `**/*.mdx`, `**/*.adoc`, `**/*.rst`
- Excluded from broad Vale: generated resource directories with dedicated artifact validation, including `codex/memories_extensions/chronicle/resources/**`

### Configuration

- Repo root MUST include `.markdownlint.yaml` when `pnpm docs:lint` is part of the contract.
- Repo root MUST include and maintain `.vale.ini` when `docs:style:changed` is part of the contract.
- If Vale package styles are configured, style checks MUST run `vale sync` before linting.

### Severity

- markdownlint failures MUST fail the docs lint contract.
- Vale errors MUST fail CI.
- Warnings/suggestions MAY be elevated repo-wide.

### Suppression / waivers (required discipline)

Markdown:

```md
<!-- vale off -- reason: legacy quote; ticket: GOV-123; expires: 2027-03-01 -->
...
<!-- vale on -->
```

MDX:

```mdx
{/* vale off -- reason: legal text; ticket: GOV-124; expires: 2027-03-01 */}
...
{/* vale on */}
```

---

## 11. Data & Config Formats (YAML / TOML / JSON)

### JSON

- JSON MUST be valid UTF-8.
- Prefer machine-generated JSON for large files; minimize hand-edited large JSON.
- Transformations MUST use `jq` (not regex).
- In JS/TS, JSON inputs at boundaries MUST be schema-validated.

### YAML

- YAML MUST be linted (repo-selected linter) and schema-validated where applicable.
- Indentation MUST be 2 spaces; tabs forbidden.
- Avoid ambiguous scalars; prefer explicit `true`/`false`.
- CI workflow YAML MUST avoid large inline scripts when a repo script exists.
- YAML suppressions (if supported by the linter) MUST follow the same waiver model.

### TOML

- TOML files MUST be syntactically valid and formatted consistently.
- Tool pinning files (e.g., `mise/config.toml`) are authoritative and MUST be reviewed like code.
- Validation MUST occur via the consuming tool in CI (mise/ruff/etc.), plus a syntax check if available.

---

## 11a. Artifact and non-code formats

Detailed rules for Mermaid, HTML, plist/XML, KDL, `.env`, signatures, checksums, generated resources, and other non-code artifacts live in [21-artifact-formats.md](./21-artifact-formats.md).

---

## 12. Naming Conventions

- Directories & files: `kebab-case`

  - Exception: constitutional governance docs may use `UPPER_SNAKE_CASE` or `PascalCase`.
- JS/TS vars/functions: `camelCase`
- Python/Rust vars/functions: `snake_case`
- Types/components: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`

---

## 13. Commits, Releases, ADRs

### Commit format (enforced)

- Commits MUST be concise and atomic.
- Prefer Conventional Commits: `feat|fix|refactor|docs|test|chore`.
- Subject MUST follow `<type>(optional-scope): <imperative summary>`.
- Subject MUST be specific and <= 72 characters.
- One logical change per commit; split unrelated edits.

### Commit body requirements

- Include `Why`, `What`, and `Impact/Risk` sections when helpful.
- `Validation` section MUST include only commands actually run.
- Validation lines MUST use this format:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
- Never invent validation.
- If no validation was run, state:
  - `Validation: not run (<reason>)`

### Commit trailer requirement

- Preserve existing trailers.
- Include this trailer exactly once as the final trailer line:
  - `Co-authored-by: Codex <noreply@openai.com>`

### Pull request template contract (enforced)

- Follow the repository PR template exactly.
- Do not add, remove, rename, or reorder template sections.
- Keep checklist item text exactly as written.
- Fill required fields with concrete, non-placeholder content.

### PR prep requirements

- Before generating PR title/description, read:
  - `AGENTS.md`
  - `CONTRIBUTING.md`
  - `.github/PULL_REQUEST_TEMPLATE.md`
- Use repo-defined command contracts from scripts/docs; do not assume `npm`.
- Prefer repository wrapper gates when defined (for example `bash codex/scripts/verify-work.sh --fast`) over ad hoc equivalents.

### PR testing and artifacts

- Populate required structured testing fields exactly as the template defines.
- Record exact commands and explicit outcomes using:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
- If a planned step cannot run, mark it `blocked` with the concrete blocker.
- Never hardcode `npm test`; use the repository canonical command contract.
- Run aggregate/deep gates when defined and required by change scope.
- Keep `CodeRabbit` and `Codex` review artifact fields non-empty when present in template.
- Preserve independent review requirements; the coding agent cannot self-approve.

### Release and architecture records

- Commits/tags MUST be signed (GPG/SSH or Sigstore/Gitsign in CI).
- Releases SHOULD follow SemVer with generated changelogs.
- ADRs are REQUIRED for significant decisions; store under `docs/adr/` (MADR template).
- Public API changes SHOULD require an ADR where the repo enables the ADR gate.

---

## 14. Toolchain & Lockfiles

- Node and package-manager contract is defined in [11-package-managers-pnpm-npm.md](./11-package-managers-pnpm-npm.md).
- Python dependency locks should remain deterministic and validated in CI.
- Rust lockfiles should remain deterministic and validated in CI.
- Frozen or locked install/build modes SHOULD be used for CI reproducibility.
