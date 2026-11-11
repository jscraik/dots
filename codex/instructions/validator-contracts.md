# Validator Contracts

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Purpose](#purpose)
- [Contract: codex preflight](#contract-codex-preflight)
- [Contract: codex config validation](#contract-codex-config-validation)
- [Contract: plan graph lint](#contract-plan-graph-lint)
- [Contract: verify-work](#contract-verify-work)
- [Failure policy](#failure-policy)
- [Evidence output](#evidence-output)

## Purpose

Define minimum contracts for scaffold and governance validators so agents run checks consistently.

## Contract: codex preflight

Evidence format:

```bash
Command: cd ${CONFIGS_CHECKOUT} && bash codex/scripts/codex-preflight.sh -> pass|fail|blocked (<reason>)
```

Pass criteria:

- Required binaries exist for the workflow.
- Required repo paths exist before edits or deeper validation.
- Git/workspace context and requested repository fragment match.
- Local Memory is retired. Preflight never probes or starts it; legacy
  `--mode` values are accepted but ignored.

Preflight does not validate TOML or the security configuration. Use the config
validator below for those checks. A preflight pass does not prove a live MCP,
or Computer Use connection.

## Contract: codex config validation

Evidence format:

```bash
Command: python3 codex/scripts/validate-codex-config.py -> pass|fail|blocked (<reason>)
```

Pass criteria:

- Root config keeps the safe solo-dev baseline.
- `plan_mode_reasoning_effort` (when present) must match supported reasoning enum values.
- The tracked root config remains the canonical policy source and `~/.codex/config.toml` is a parseable regular runtime copy that does not share its inode.
- Every profile explicitly declares the five key execution axes.
- Exceptional profiles using `never`, `danger-full-access`, or `live` are narrowly scoped and intentional.
- Active MCP servers declare stable startup metadata and avoid ephemeral package execution.
- OTel and shell-environment settings remain aligned with the current privacy baseline.

## Contract: plan graph lint

Evidence format:

```bash
Command: python3 ${CODEX_POLICY_SOURCE}/scripts/plan-graph-lint.py <plan-file> -> pass|fail|blocked (<reason>)
```

Pass criteria:

- Plan parses successfully.
- Task IDs are nonempty and unique; no particular prefix is enforced.
- `depends_on` references valid in-plan tasks.
- No self-dependencies.
- Graph is acyclic.

## Contract: verify-work

Evidence format:

```bash
Command: bash ${CODEX_POLICY_SOURCE}/scripts/verify-work.sh -> pass|fail|blocked (<reason>)
```

Pass criteria:

- All required checks pass.
- `codex-preflight` passes.
- `execpolicy-rule-validation` passes.
- `codex-config-validation` passes.
- `plan-graph-lint` is available when present and passes if invoked.
- `verify-work` reports skips explicitly with reason.
- Zero failed checks in summary.

## Failure policy

- Stop checks and claims that depend on a failed validator; continue independent authorized work.
- Fix introduced failures and classify pre-existing or environmental blockers.
- Do not claim a blocked lane passed. Reuse unchanged aggregate coverage.

## Evidence output

For each validator run, capture:

- command executed
- exit code
- one-line result (`pass`, `failed`, or `skipped`)
- short reason for failures/skips
