# Artifact Format Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Mermaid diagrams](#mermaid-diagrams)
- [Static HTML and browser artifacts](#static-html-and-browser-artifacts)
- [Launchd plist and XML](#launchd-plist-and-xml)
- [KDL, terminal, and tool profile files](#kdl-terminal-and-tool-profile-files)
- [Environment files](#environment-files)
- [Generated resources, signatures, and checksums](#generated-resources-signatures-and-checksums)
- [Enforcement](#enforcement)

## Scope

- This module covers maintained artifact formats that are present in this repository but are not owned by the language-specific modules.
- Follow this module for `.mmd`, Mermaid fenced blocks, `.html`, `.plist`, `.kdl`, `.env`, `.command`, generated resource files, media assets, signatures, and checksums.
- When an artifact is generated, the generator and regeneration command are the source of truth; do not hand-edit generated output unless the generator is unavailable and the reason is recorded.

## Mermaid diagrams

- Mermaid files and fenced `mermaid` blocks MUST parse before a diagram change is considered verified.
- Prefer `flowchart` syntax for new flow diagrams unless an existing diagram family already uses another Mermaid diagram type.
- Keep labels quoted when they contain punctuation, parentheses, or markdown-sensitive characters.
- Avoid embedding large HTML fragments in diagram labels; use Markdown strings or shorter labels where possible.
- For diagram-rendering changes, run the repo diagram freshness or Mermaid parser gate when available.

## Static HTML and browser artifacts

- Static HTML MUST be valid enough for the consuming browser/tool and MUST keep script/style dependencies explicit.
- Do not inline secrets, local absolute workstation paths, or environment-specific tokens.
- Keep accessibility basics intact: document language, meaningful titles, semantic structure, keyboard-reachable controls, and text alternatives for meaningful images.
- If HTML is an exported/generated artifact, update the source template or generator first.

## Launchd plist and XML

- `.plist` files MUST remain valid XML property lists and SHOULD be checked with `plutil -lint` when available.
- Launchd labels, program paths, working directories, and environment variables MUST match the repository's managed configuration contract.
- Prefer explicit `ProgramArguments` arrays over shell-wrapped commands unless shell behavior is the point being tested.
- Do not write user-specific absolute paths into reusable templates unless the template explicitly documents substitution.

## KDL, terminal, and tool profile files

- KDL and terminal profile files MUST preserve the target tool's syntax and ordering expectations.
- Keep generated profile files tied to a script or template when practical.
- Avoid mixing manual edits with generated blocks unless the file documents a stable manual section.

## Environment files

- `.env` files MUST NOT be committed with real secrets.
- Example environment files MUST use inert placeholders and document the owning service or script.
- Scripts that read environment files MUST fail closed on missing required variables and avoid printing raw values.
- Runtime-only environment files in this subtree are local operational state, not style examples.

## Generated resources, signatures, and checksums

- Generated JSON, Markdown, HTML, diagrams, and media assets MUST identify or imply their generator through nearby script names, docs, or validation evidence.
- Generated Chronicle resource filenames preserve source timestamps and capture IDs for traceability; those generated names are exempt from the general kebab-case filename rule.
- Signature (`.sig`) and checksum (`.sha256`) files MUST be refreshed together with the artifact they protect.
- Binary/media assets (`.png`, `.webp`, `.svg`) MUST have a review path appropriate to their use: visual diff, checksum, render check, or source-generator evidence.
- Large generated artifacts SHOULD be excluded from broad prose/style lint unless a dedicated validator owns them.

## Enforcement

- Artifact-format changes MUST run the nearest executable validator:
  - `pnpm lint` from the parent repo root for JSON/YAML/frontmatter/config checks.
  - `pnpm docs:lint` from the parent repo root for maintained Markdown when in scope.
  - `bash scripts/verify-work.sh --fast` from the codex subtree root for Codex runtime and instruction changes.
  - Format-specific checks such as `plutil -lint`, Mermaid parsing, `jq`, `yq`, or consuming-tool validation when the touched format has a tool.
- Validation evidence MUST include exact command text, working directory when ambiguous, and outcome:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
