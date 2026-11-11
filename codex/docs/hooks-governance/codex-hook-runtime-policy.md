# Table of Contents

- [PreToolUse](#pretooluse)
- [Arbitration Policy](#arbitration-policy)
- [Timeout Classes](#timeout-classes)
- [Other Event Notes](#other-event-notes)

## PreToolUse

`PreToolUse`, `PermissionRequest`, and `PostToolUse` match practical `Bash`,
`apply_patch`, `Edit`, and `Write` payloads. MCP tool names are also matcher
inputs in the runtime, but this policy pack only installs Bash and edit-tool
guards.

`PreToolUse` blockers must use supported block semantics:

- `hookSpecificOutput.permissionDecision: deny`
- legacy `decision: "block"`
- exit code `2`

`git commit --no-verify` is treated as a non-bypassable policy violation and is
always blocked by `PreToolUse`. `git push --no-verify` is blocked by default, but
`codex/hooks/pre-tool-use-guard.sh` permits an audited break-glass path only when
`CODEX_HOOK_BYPASS_ACK`, `CODEX_HOOK_BYPASS_REASON`, and
`CODEX_HOOK_BYPASS_LOG` are all present; `codex/scripts/validate-codex-hooks.sh`
exercises both the default block and logged allow paths.

`continue:false` is unsupported for `PreToolUse` blocking and must not be used as the controlling deny path.

## Arbitration Policy

Concurrent hook outcomes are normalized to one canonical decision per trigger event:

- `block`
- `allow-with-warning`
- `allow`

Decision precedence:

1. Any `block` from a canonical owner wins.
2. Non-canonical `block` outcomes are downgraded to warning unless a canonical owner also blocks.
3. Any warning yields `allow-with-warning`.
4. Otherwise `allow`.

Deterministic winner tie-break key:

1. owner-layer precedence (`git_local` > `project_codex` > `global_codex`)
2. lexical `source_path`
3. lexical `gate_id`
4. lexical `reason`

Canonical decision records include:

- `gate_id`
- `owner_layer`
- `source_path`
- `winning_reason`
- `suppressed_reason_count`

Implementation source:

- `codex/scripts/hook-governance/hook_runtime_policy.py`
- `codex/scripts/hook-governance/arbitrate_hook_results.py`

## Timeout Classes

Hook policy is encoded by timeout class and failure posture:

- `PreToolUse`: `pre_safety_fail_closed` (block only on supported explicit deny semantics)
- `PostToolUse`: `post_quality_advisory_fail_open` (warn and continue)
- `SessionStart`: `startup_non_blocking` (degrade gracefully)
- `UserPromptSubmit`: `prompt_guard_fail_closed`
- `Stop`: `stop_guard_fail_closed`

## Other Event Notes

- `SessionStart.matcher` is currently limited to `startup`, `resume`, and `clear`
  in the governance contract. Enrichment remains non-blocking and degrades
  gracefully for every source.
- `Stop` and `UserPromptSubmit` do not support matcher filtering.
