# Codex Platform Readiness

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Static contract](#static-contract)
- [Runtime evidence](#runtime-evidence)
- [Change boundaries](#change-boundaries)

## Static contract

Treat `codex/config.toml`, hooks, requirements, validators, and projected
symlinks as the canonical local control plane. Validate configuration with
`python3 codex/scripts/validate-codex-config.py`, hooks with
`bash codex/scripts/validate-codex-hooks.sh`, and projections with
`bash codex/scripts/audit-codex-symlinks.sh`.

## Runtime evidence

Static validation does not prove Desktop, Browser/Computer Use, plugin, MCP, or
app-server behavior. Use the relevant isolated runtime smoke check and report
its result separately. If static configuration passes but startup fails, route
the remaining issue through `$mcp-startup-triage` rather than changing config
blindly.

Use the currently exposed tool's documented startup API. For a `cua_repl`
surface that documents it, `cua.getState()` proves returned discovery data for
that task. It does not prove window inspection, application control, helper
installation, vault access, or future-session reliability. Verify each capability
only when the task requires it. Treat another task's reported success as supplied
evidence, not a probe executed in this task. A settings label such as “Install”
does not establish the helper's implementation or why it is absent.

## Change boundaries

Do not enable a plugin, hook, or runtime feature merely because an older local
source checkout described it. Verify that the current configuration and
validator support it, make the smallest tracked source change, and project to
`~/.codex` only through a separately authorized runtime operation.
