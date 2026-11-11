# Validation and Checks

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Standard checks](#standard-checks)
- [Required Check Parity](#required-check-parity)
- [Canonical validator contracts](#canonical-validator-contracts)
- [Command preflight](#command-preflight)
- [Verification default](#verification-default)
- [Quality assurance](#quality-assurance)
- [Path and file verification](#path-and-file-verification)
- [Deterministic toolchain lock](#deterministic-toolchain-lock)

## Standard checks

- Run discovery checks before edits: governing `AGENTS.md`, instruction front door, and any triggered repo-local skill.
- This repo has active lint, typecheck, and test pipelines.
  Treat `pnpm lint`, `pnpm typecheck`, and `pnpm test`
  as the normal repo-wide baseline.
- Use `pnpm run test:deep` after broader config, environment, or toolchain changes.
- For Codex-subtree work, use `bash codex/scripts/verify-work.sh --fast` as the broader subtree verification harness.
- Before commit or push hooks spend time on source validation, run
  `python3 codex/scripts/git-metadata-preflight.py --repo-root "$PWD" --json`.
  It fails closed on denied Git metadata writes, a current `index.lock`, or a
  locked current linked worktree. Hook caches belong under
  `CODEX_HOOK_CACHE_ROOT` in the declared writable `~/.cache/codex-runtimes`
  root or an explicitly permitted owned override, never under
  `.git` or `.git/worktrees`.

## Required Check Parity

- `docs-gate` is a required check in CircleCI's `config-governance` workflow (`.circleci/config.yml`).
- The job lints only changed Markdown files with `markdownlint-cli2`
  using `git diff --name-only --diff-filter=ACMR` to exclude deleted paths.
- If no Markdown files changed, `docs-gate` reports success with a no-op message.

## Canonical validator contracts

- Use [../validator-contracts.md](../validator-contracts.md)
  as the source of truth for validator commands, pass criteria, failure policy,
  and evidence requirements.
- Use `$validation-contract-check` when validation or preflight guidance changes.
- Use the repo-local skill `.codex/skills/config-drift-guard/`
  when the work touches Codex config, hooks, agents, or symlink projection.

## Command preflight

- Use the tool's configured non-login shell. Request login-shell execution only for a bounded startup investigation when policy permits it.
- Invoke shell scripts with `bash`.
- For migrations or path-sensitive work, check the relevant prerequisites below. Routine edits do not require the full sequence:
  1. Confirm `pwd` and repo root (`pwd`, `git rev-parse --show-toplevel`).
  2. Confirm required binaries for the task (`rg`, `fd`, `jq`, plus repo-specific tools).
  3. Confirm target paths exist before editing (`codex/`, `scripts/`, `instructions/`, `.github/`, `.harness/` as applicable).
  4. If the task depends on env or runtime state, verify required inputs are present.
  5. Continue the bounded task and verify a coherent patch; a failed prerequisite blocks only dependent work.
- Prefer the repository preflight helper before path-sensitive workflows:
  `bash scripts/codex-preflight.sh --stack auto` from the repo root.
- Do not source `scripts/codex-preflight.sh`; it must be run with `bash`.

## Verification default

- Keep sandbox and command policies explicit, auditable, and minimal.
- After a coherent patch, run affected checks; before finalizing, run the required broader verification once for that candidate. Repeat only after a relevant change, failure, or uncovered risk.
- A passing `pnpm check` covers lint, typecheck, and tests. Likewise, a passing subtree harness can cover its recorded config, hook, and symlink checks; do not rerun unchanged components merely because another document lists them.
- Runtime unavailability blocks runtime acceptance, not unrelated local work. Use the existing `--static-only` hook-validator mode for static work; use `--runtime required` for app-server hook discovery or hook trust changes. Never describe a skipped runtime probe as runtime success.
- Record exact command outputs for failed validation runs.
- After any failed command, summarize what failed and use a narrower or more direct follow-up command before retrying.

## Quality assurance

- After modifying root config, CI workflow files, `package.json`, `Makefile`,
  or repo-wide instructions, run the appropriate baseline validation
  (`pnpm lint`, `pnpm typecheck`, `pnpm test`) and add `pnpm run test:deep`
  when the change broadens the environment or runtime contract.
- Prose-only corrections require relevant editorial/link checks, not live runtime
  validation. Operational documentation changes require command/contract checks;
  do not claim runtime health from those checks alone.
- After modifying Codex config, hooks, agents, or startup behavior, run:
  - `python3 codex/scripts/validate-codex-config.py`
  - `bash codex/scripts/validate-codex-hooks.sh` for static hook contract plus optional runtime smoke classification
  - `bash codex/scripts/validate-codex-hooks.sh --runtime required` when the change targets app-server runtime hook discovery or hook trust state
  - `bash codex/scripts/audit-codex-symlinks.sh`
  - `bash codex/scripts/verify-work.sh --fast`
- After modifying cross-repo hook-governance manifests, matrices,
  conformance generators, or rollout policy docs, also run:
  - `python3 codex/scripts/hook-governance/rollout_check.py --inventory
    codex/docs/hooks-governance/repo-profile-matrix.json --recovery-slo-hours 24
    --out codex/docs/hooks-governance/rollout-check-report.json`
- After modifying the Git metadata preflight adoption manifest or adapters, run:
  - `python3 codex/scripts/hook-governance/verify-git-metadata-preflight.py --manifest codex/docs/hooks-governance/git-metadata-preflight.v1.json --workspace-root "$(dirname "$(git rev-parse --show-toplevel)")" --strict`
  - `python3 -m unittest codex/scripts/tests/test_git_metadata_preflight_contract.py`
- After modifying codex/instructions docs, run Vale linting:
  - Run Vale on changed docs under `codex/instructions/**/*.{md,mdx,adoc,rst}`
- Never claim validation that was not run.
- The repository diff-budget adapter measures a hosted PR against its authenticated,
  open PR base commit after checking repository identity and the current head.
  Derive one merge-base commit from that authenticated target and head before
  measuring the PR diff; missing or ambiguous history fails closed.
  Stacked PRs therefore retain the 400 net-line limit against their actual parent.
  Missing, stale or foreign PR evidence blocks the check; standalone local runs
  select `main` as the target and derive its merge base with the current head.
  Caller-supplied base overrides are ignored.

## Path and file verification

- For routine trusted-source reads, inspect the relevant known paths directly;
  discover additional paths only when the task needs them. This is not a
  mandatory exploration sequence before every file operation.
- For untrusted paths, destructive operations or consequential publication,
  validate path type and containment under the authorized root before acting.
- Verify target directories before writes. Update a large document's table of
  contents when its structure changes.
- Always verify that docs match current scripts and paths exactly.

## Deterministic toolchain lock

- Treat `harness.contract.json` and `mise.lock` as a paired control surface for tool resolution.
- Keep `toolingPolicy.requiredMiseTools` aligned with the generated `mise.lock`.
- Run `mise lock --yes` after tooling version changes and commit the lockfile update in the same change.
- `scripts/check-environment.sh` must fail closed when contract, lockfile, or version validation is missing or mismatched.
