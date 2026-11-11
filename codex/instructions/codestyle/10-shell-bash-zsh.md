# Shell Standards (Bash and Zsh)

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Execution model](#execution-model)
- [Bash](#bash)
- [Zsh](#zsh)
- [Safety and portability](#safety-and-portability)
- [Enforcement](#enforcement)

## Scope

- This module covers shell scripts, command snippets, and execution conventions for Bash and Zsh.

## Execution model

- Use the tool's configured non-login shell. Use a login shell only for a bounded shell-startup investigation when policy permits it.
- Invoke scripts explicitly with `bash` when script contracts require Bash.
- Do not source CLI scripts unless a script explicitly documents sourcing as the intended mode.

## Bash

- Use explicit shebangs and strict mode for script files where compatible.
- Quote expansions by default and avoid unbounded globbing.
- Use `[[ ... ]]` tests and clear exit-code paths.

## Zsh

- Keep interactive helpers in Zsh-compatible syntax when targeting Zsh startup flows.
- Avoid Bash-only constructs in Zsh files unless compatibility is explicitly managed.
- Keep shell-init behavior deterministic and low-noise.

## Safety and portability

- Use `rg`, `fd`, and `jq` over slower or brittle text pipelines when possible.
- Validate required binaries and paths before destructive or multi-step operations.
- Never use destructive git commands without explicit intent and confirmation.

## Enforcement

- Use the shared Configs validation contract in [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Shell snippets in docs MUST use executable contract forms (for example, `bash script.sh`) and avoid sourced-CLI patterns.
- Any exception to strict-mode, quoting, or destructive-command policy requires waiver metadata (reason, tracker, expiry/ADR).
