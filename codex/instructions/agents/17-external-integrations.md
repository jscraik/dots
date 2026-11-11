# External Integrations

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Authentication](#authentication)
- [MCP and API failures](#mcp-and-api-failures)
- [Hosted CI](#hosted-ci)

## Authentication

Use the smallest value-blind probe that the relevant integration documents.
Do not dump environment variables, source a credential FIFO, or treat one
1Password route as proof of another. Stable FIFO injection, beta environment
loading, 1Password MCP, and native Git signing are independent contracts; see
[1Password.md](../1Password.md) for their supported commands.

## MCP and API failures

For a Codex startup or MCP failure, inspect `codex mcp list` and use
`$mcp-startup-triage`. Confirm the first failing layer before retrying. Do not
assume `op account list`, an environment dump, or an unrelated API probe proves
that an MCP server is authenticated.

## Hosted CI

Required checks are repository-specific. Derive them from the current PR,
branch-protection contract, and repository CI configuration. Preserve CI log
provenance and rerun only the affected job or workflow when the provider
supports that route.
