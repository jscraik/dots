# Tooling and Command Policy

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Repo-safe command baseline](#repo-safe-command-baseline)
- [Verification commands](#verification-commands)
- [Command evidence requirements](#command-evidence-requirements)
- [Unavailable tools](#unavailable-tools)

## Repo-safe command baseline

- Prefer `rg` for content search, `fd` for file discovery, and `jq` for JSON.
- Use the tool's configured non-login shell. Check PATH when a required binary is missing; do not enable a login shell as a blanket workaround.
- Check availability when a task requires a particular command.
- Avoid inventing commands or paths; verify each referenced path exists first.
- Ask before changing dependencies or system settings.

## Verification commands

Use for repository-safe discovery and validation:

- `rg --files`
- `rg --files | rg 'AGENTS.md|README.md|\.md$'`
- `fd AGENTS.md instructions`
- `jq 'keys' package.json`

## Command evidence requirements

- Treat commands and paths as facts only if observed from the repo.
- Capture outputs for any gating failure.
- Keep outputs short and include failures in the change record.

## Unavailable tools

Use an available read-only equivalent for ordinary discovery when a preferred
tool is missing, such as `rg --files` instead of `fd`. Do not install a new
dependency merely to satisfy a preferred-tool list. A validator that explicitly
requires a missing binary remains blocked; record that boundary and continue
independent work. A fallback is not proof that the unavailable validator passed.
