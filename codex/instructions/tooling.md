---
title: Tooling Contract
scope: workstation routing, not an installed-package inventory
---

# Tooling Contract

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Source of truth](#source-of-truth)
- [Discovery and validation](#discovery-and-validation)
- [Browser evidence](#browser-evidence)
- [Authentication and integrations](#authentication-and-integrations)
- [Runtime failures](#runtime-failures)

## Source of truth

Do not treat this document as a version or installation inventory. Resolve the
toolchain from the owning repository's `package.json`, lockfile, `.mise.toml`,
`Brewfile`, and documented scripts. In Configs, `.mise.toml` owns deterministic
repository pins, including the browser-evidence tools; `mise/config.toml` owns
the broader workstation inventory. Use the repository's package manager and
wrappers rather than installing a global substitute.

For Configs, `pnpm`, `package.json`, `Makefile`, and the scripts under
`codex/scripts/` define the local command contract. Check a tool's presence with
`command -v <tool>` and its supported flags with `<tool> --help`; do not infer a
version or installed MCP state from this file.

## Discovery and validation

- Prefer `rg` for repository search, `fd` or `rg --files` for discovery, and
  `jq` for JSON.
- Use the tool's configured non-login shell and invoke shell scripts explicitly with
  `bash`.
- Use the narrowest repository-native validation first. In Configs, the normal
  baseline is `pnpm lint`, `pnpm typecheck`, and `pnpm test`; Codex-subtree work
  also uses `bash codex/scripts/verify-work.sh --fast`.
- CircleCI CLI probes use the documented opt-out variable:
  `CIRCLECI_CLI_TELEMETRY_OPTOUT=1 circleci version`.

## Browser evidence

Resolve the pinned `agent-browser`, `agentation`, and `agentation-mcp` versions
from `.mise.toml`; do not install ad hoc global copies. Use `agent-browser` for
the repository's browser rendering path and `agentation` through the
`agentation-mcp` executable for annotation feedback. When a harness stage
requires `browser-evidence-artifacts`, preserve the rendered output and its
repository-defined evidence metadata; tool availability alone does not prove
that the browser evidence stage passed.

## Authentication and integrations

The supported 1Password routes are deliberately separate:

- stable local environment injection through the owner-managed FIFO;
- beta environment injection through `op-beta --environment`;
- the 1Password MCP route; and
- native Git signing through `/Applications/1Password.app/Contents/MacOS/op-ssh-sign`.

Follow [1Password.md](./1Password.md) for value-blind probes and boundaries.
Never source, copy, print, or substitute an environment FIFO. Use `codex mcp
list` to inspect MCP registration; a listed server does not prove a successful
handshake or tool call. Managed server descriptors belong in the canonical
`codex/config.toml`, then the runtime copy is reconciled from it. Credentials
remain in their supported authentication channel, never in tracked config.

The unused local GitHub and RepoPrompt MCP transports are retired. GitHub
access uses the connected plugin. Reintroducing the local GitHub server still
requires every existing per-tool approval guard; absence is not permission to
configure a malformed or less restrictive replacement.

## Runtime failures

When the desktop hook bridge omits a shell tool's requested working directory,
relative validation paths are resolved against the chat directory and can be
rejected. Invoke the owned entrypoint with its canonical absolute path, such as
`bash ${CODEX_POLICY_SOURCE}/scripts/verify-work.sh --fast`.
This is the same allowlisted script, not a policy bypass. Do not relax the
hook or infer an unreported execution directory. Hook callers that supply
`tool_input.workdir` are supported alongside `tool_input.cwd`.

If a configured tool is unavailable, first identify whether the failure is a
repository dependency, shell PATH, authentication, sandbox, or runtime-startup
problem. For MCP, Browser, Computer Use, `mise`, or Desktop startup failures,
use `$mcp-startup-triage`. Keep an external or provider failure separate from
source and local-validation claims.
