# Canonical Command Rules

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Loaded layers](#loaded-layers)
- [Validation](#validation)
- [Changes and authority](#changes-and-authority)

## Loaded layers

Codex loads the canonical files in `~/.codex/rules/` together:

- `foundation.rules`: reviewed read/build/test allowlist.
- `default.rules`: two exact, fixed-output authentication canaries.
- `automation.rules`: narrowly reviewed automation support.
- `guard.rules`, `pr.rules`, `project.rules`: prompts and prohibitions.

There is no separate audit/work mode selected by a filename. Duplicate
`gold-standard.rules` and `work.rules` aliases are retired. The most restrictive
matching rule applies; no match falls back to sandbox and approval policy,
not automatic denial or permission.

## Validation

From the Configs repository root:

```bash
python3 codex/scripts/validate-execpolicy-rules.py
```

The validator checks the complete loaded rule set, rejects aliases, and tests
important allow/prompt/forbid interactions. A hand-picked subset is only a spot
check, not proof of effective policy.

## Changes and authority

Keep one-off approvals out of permanent rules. A recurring exception needs a
bounded consumer, justification, positive and negative examples, and regression
coverage. Do not widen the authentication canaries to arbitrary auth commands.
Command rules do not replace task authorization, runtime hooks, or
`requirements.toml` configuration constraints.

Named test modules and package checks still require an authorized task and
inspection of fixture side effects. Both `pnpm check` and `pnpm run check`
select the same named validation permission. Unlisted `run` scripts fall back
to sandbox and approval policy; they are not auto-allowed.

Arbitrary Python, `find`, `fd`, `rg`, `cat`, `less`, `date` and Git
`diff`/`log`/`show` fall back to sandbox and approval policy: their prefixes
cannot prove safe arguments. Removing an allowance is not a blanket denial.
The retained positional `.env` prompt is defense in depth, not a secret-reading
firewall. Task authority and filesystem protections still apply to all readers.
Single-file `cat` exceptions are removed because they also accepted trailing
secret paths. Ordinary `rg --files` remains a useful discovery command within
the sandbox. The routing validator parses active
CommonMark links, including reference links, while ignoring code and comments.
