> Retained Configs reference. Its package and workstation recipes remain
> Configs-scoped; use [migration scope](instructions/migration-scope.md) and the
> [dots validation contract](../README.md#verify-locally) for this inactive port.

# Codex Configuration (Canonical)

This repository is the canonical source for local Codex workstation
configuration, guardrails, agents, prompts, and automation support artifacts.

## Table of Contents

- [Automation storage model](#automation-storage-model)
- [Multi-machine agent sharing](#multi-machine-agent-sharing)
- [Configuration ownership and projection](#configuration-ownership-and-projection)
- [Canonical paths](#canonical-paths)
- [Canonical checkout and saved worktrees](#canonical-checkout-and-saved-worktrees)
- [OSS execution profiles](#oss-execution-profiles)
- [Policy enforcement baseline](#policy-enforcement-baseline)
- [Git and GitHub capability boundary](#git-and-github-capability-boundary)
- [Managed configuration rollout](#managed-configuration-rollout)
- [Maintenance launchd jobs](#maintenance-launchd-jobs)
- [Verification commands](#verification-commands)
- [Repository layout](#repository-layout)

## Automation storage model

- Scheduled automation definitions and scheduler state are runtime-owned at
  `$CODEX_HOME/automations/<automation-id>/automation.toml` and in the app's
  scheduler registry. `~/.codex/automations` must be a real directory, never
  a symlink into this repository.
- Create, pause, update, and delete schedules through the Codex automation
  integration. Deleting only an `automation.toml` file is not deletion: the
  scheduler can materialize its registry record again after restart.
- `codex/automations/` contains durable routing material and historical
  artifacts only. It is intentionally not projected into `$CODEX_HOME`.

## Multi-machine agent sharing

This workstation uses task-scoped generic collaborators. Named role TOMLs and
`[agents.<name>]` registrations are retired by local policy, not because all
Codex runtimes lack custom-agent support. Follow the current delegation tool's
schema; a task label alone does not select a configured role.

Route collaborators by explicit task capability, authority, evidence
requirements, and stop condition. Do not create a role registry, manifest
projection, or prompt guidance that claims a task name selects a named role.

Git history retains the prior role prompts. Reintroduce a named role only when
Desktop documents a supported selection field and a real Desktop invocation
proves that it loads the configuration.

## Configuration ownership and projection

Automatic review stays enabled with `approval_policy = "on-request"` and
`approvals_reviewer = "auto_review"`. Root and standalone profiles omit
`auto_review.policy`: that setting replaces the active reviewer policy rather
than extending it. The validator rejects local overrides; runtime reconciliation
restores canonical policy after backing up the runtime file, while retaining
Desktop-owned Computer Use plugin consent.
Signing and PR authority remain in the existing instructions and execution
controls. Do not copy `policy_template.md` into the policy field: it is the
surrounding reviewer template, not the complete active security policy.
See the [official auto-review documentation](https://learn.chatgpt.com/docs/sandboxing/auto-review).

The unused `canary-alpha`, `cron-automation`, `d`, `deep-review`, and `fast`
profiles are retired. Their standalone files and projection entries are removed;
`docs` and the six OSS profiles remain. Historical reports are not installation
instructions and must not be used to restore the retired profiles.

The terminal CLI is pinned through mise to `npm:@openai/codex@0.153.4`, matching
the Desktop runtime checked on 2026-09-05. Avoid a second npm-global Codex copy:
it can shadow the mise package. Verify the resolved executable with
`codex --version` after installation.

Shell environment inheritance starts from `all`, then applies the explicit
`include_only` allowlist and default secret exclusions. `inherit = "none"`
cannot propagate an allowlisted parent variable. Keep the allowlist and
`ignore_default_excludes = false` together; do not replace them with a wildcard.
Allowlist patterns must begin with a literal letter or underscore. Namespaced
globs such as `LC_*` and `NX_*` remain valid; leading wildcard, character-class,
alternative, and empty patterns block repair without writing the runtime file.
Matching is case-insensitive with `*` and `?` wildcards, not regular expressions.
Patterns such as `SSH_*` or `NODE_REPL_*` that match protected runtime names also
block repair. Exact retired entries keep their existing removal path.
An isolated Codex 0.153.4 app-server probe verified allowlisted propagation and
default secret filtering using dummy variables, without model requests.
Runtime reconciliation restores inheritance and default exclusions only after
validating the allowlist, and blocks malformed reviewer settings without writing.

Compaction uses the runtime threshold instead of a fixed 500,000-token limit;
tool output is capped at 10,000 tokens. The shorter handoff prompt preserves
authority, dirty-file ownership, distinct evidence states, and the next action
without requiring empty sections. The canonical configuration does not opt into
experimental context management. Runtime reconciliation removes the previous
managed opt-in during canonical reconciliation; unsupported layouts block
without replacement. The retired `enable_fanout` flag is removed. The checked-in schema
accepts a boolean or a closed table containing only boolean `experimental_mode`
at root and profile scope. The validator rejects missing or inconsistent schema
definitions, including extra declared table properties. Schema acceptance does
not require enabling the feature in the canonical configuration.

Repository writes come from the active workspace or bounded permission grants,
not global write roots for Configs and Agent-Skills. The
validator rejects enclosing parent roots and symlink aliases across permission
profiles. Global filesystem writes require exact paths, optionally ending in
`/**`; other wildcard write grants are rejected without expanding them.
Read and deny patterns remain permitted. The authentication FIFO has exact read access rather than being
declared a workspace directory.
Session evidence access is independent of project trust; confirmed non-project
trust entries and the duplicate Agent-Skills spelling are removed. Existing
Git repositories and Desktop-owned scratch-task entries are preserved.

The canonical system skill creator and installer are enabled; older duplicate
skill paths remain masked. Existing runtime-disabled legacy plugins stay
disabled in the canonical config. The absent Chrome DevTools executable is no
longer registered as a server; that removal does not prove the app-owned
Browser or Computer Use service works.

The runtime reconciler validates the canonical source, saves a private backup,
and restores canonical policy while preserving Desktop-owned Computer Use plugin
consent. Saved configuration does not prove an already-active
task has reloaded it.

The default is `gpt-6-astra` with `model_reasoning_effort = "low"`
("light" reasoning), `model_verbosity = "medium"`, and
`model_reasoning_summary = "auto"`. Named review and specialist
profiles retain their workload-specific settings. Existing tasks can retain
their own model selection; the saved default does not prove an active task
has switched models.

`${CODEX_POLICY_SOURCE}/config.toml` is the version-controlled
canonical source for the entire config. `${HOME}/.codex/config.toml`
is an isolated regular-file copy. Its parsed policy must match canonical policy
except for Desktop-owned Computer Use plugin tables. When policy drifts, repair
replaces other runtime-only fields, comments, and formatting. Desktop plugin
consent remains in the runtime file and is not copied into the repository.

The projection contract therefore has two parts:

1. `scripts/link-configs.sh` manages links and checks runtime policy agreement.
2. `codex/scripts/reconcile-config-projection.sh` invokes
   `repair-runtime-config-drift.py` to restore validated canonical policy plus
   Desktop-owned Computer Use plugin tables, retaining a private backup and
   checking for observed concurrent changes.

Managed strings include the default model, developer instructions, plan-mode
reasoning and verbosity defaults, compaction prompt path, and Desktop commit, PR, and
PR-watch instructions. Other runtime-only state is removed by reconciliation
and remains recoverable in the reported backup. Desktop-owned Computer Use
plugin tables, including disabled consent and nested settings, are preserved.
The ordered `project_doc_fallback_filenames` list is also managed. Keep
`AGENT.md` and `CONTRIBUTING.md` as the canonical fallback names; architecture,
vocabulary, and changelog documents remain selectively loaded references,
not instruction fallbacks. Make intentional configuration changes in the repository first.
The `workspace-net` and `readonly-net` profile descriptions also follow the
canonical labels. This label synchronization does not change filesystem roots,
network access, profile selection, or approval policy.
Set `model_reasoning_effort` in the canonical repository configuration;
runtime-only changes do not survive full-file reconciliation.
The config-drift guard checks the canonical configuration and live runtime
policy agreement. To inspect synchronization without writing, run:

```bash
python3 codex/scripts/repair-runtime-config-drift.py --config-path "${CODEX_HOME:-$HOME/.codex}/config.toml" --check --json
```

When repair is authorized, use the same command with `--repair` and a unique
`--backup-path` instead of `--check`. Verify the repaired file again; a passing
file check does not prove an existing Desktop task has reloaded its settings.

Projection checks also report retired `canary-alpha`, `cron-automation`, `d`,
`deep-review`, and `fast` profile links. Repair archives only exact symlinks to
removed canonical profile files in a unique `.retired-profile-backups-*`
directory inside the selected Codex home. `--dry-run` previews the operation;
custom files and unknown symlink targets are preserved and require manual review.
No profile is retired while its canonical source or projection entry remains.

The launchd reconciler watches the runtime `config.toml` and also runs every ten
minutes. It restores parsed canonical policy agreement while retaining Desktop-owned
Computer Use plugin consent after validation and backup.
Never repair the boundary by copying `~/.codex/config.toml` into Git.
Agreement is point-in-time evidence: a running app can introduce later drift.

## Canonical paths

- Runtime schedule path:
  - `${HOME}/.codex/automations/<automation-id>/automation.toml`
- Repository artifact path (not a runtime schedule source):
  - `${CODEX_POLICY_SOURCE}/automations/`

The legacy root `automation.toml` template and projection are retired. Projection
repair must not recreate a schedule source; use the app's automation controls.

## Canonical checkout and saved worktrees

The checkout that owns the current delivery is the only source checkout that
may project configuration. Saved branches and linked worktrees are recovery or
review parcels; they are never alternate configuration sources and must not be
copied into `~/.codex`.

Before a branch or worktree is retired, inventory it with
`git worktree list --porcelain` and `bash codex/scripts/audit-worktrees.sh --check`.
Retain dirty, locked, detached, or owner-unknown parcels until their owner has
classified their changes and no unique commits remain. Cleanup is a separate,
explicit lifecycle action. This keeps a stale parcel from silently reintroducing
runtime policy while preserving recovery evidence.

## OSS execution profiles

The existing execution launcher also accepts `review --base <verified-base-sha>`.
For a no-home-write review, set `CODEX_EXEC_FORCE_FALLBACK=1` and point `CODEX_EXEC_RUNTIME_ROOT` and `CODEX_EXEC_DIAGNOSTIC_ROOT` at distinct, dedicated directories beneath an owned temporary directory.
Reserve the diagnostic root exclusively for retained launcher failures; retention prunes older subdirectories. Do not share either root with unrelated caller artifacts.
Fallback skips caller-home lock probes and keeps copied config, SQLite state and retained diagnostics in the disposable runtime. It does not copy authentication credentials or waive model, export, signing or review gates.
Missing authentication blocks review. Bind the candidate and base before launch and recheck both afterwards.
Launch from the verified candidate checkout, not the launcher's installation directory. The generic launcher preserves the invoking working directory and native Codex arguments, but cannot infer the intended repository from a base SHA.
Verify repository identity and candidate HEAD before interpreting its review.

The projected OSS eval lanes are deliberately narrow and read-only. They
disable inherited MCP servers, apps, plugins, and code mode so an eval cannot
silently reach workstation connectors or Computer Use. Use the normal global
profile when Browser, Chrome, or Computer Use is required.

| Profile        | Provider     | Model                          |
| -------------- | ------------ | ------------------------------ |
| `oss-local`    | local Ollama | `qwen3.5:9b-mlx`               |
| `oss-inspect`  | local Ollama | `gemma4:12b-mlx`               |
| `oss-security` | local Ollama | `h4rithd/coder:14b`            |
| `oss-cloud`    | Ollama Cloud | `deepseek-v4-flash:0731-cloud` |

For a local run, keep Ollama serving on its documented local endpoint and
pass the model explicitly when using `--oss`. Use the repository wrapper as
the supported entrypoint: it probes the Codex installation and SQLite lock
boundaries, and when the managed `~/.codex` runtime returns `EPERM` it creates
a disposable lockable `CODEX_HOME` under `~/.codex/tmp` (or `TMPDIR`), links
only the canonical base config and selected profile, and overrides
`sqlite_home` inside that runtime. Successful runs remove the temporary
runtime; failed runs retain at most three bounded diagnostic directories under
`~/.codex/tmp/codex-exec-failures`.

```sh
ollama serve
bash ${CODEX_POLICY_SOURCE}/scripts/run-codex-exec.sh \
  --profile oss-local --oss --local-provider ollama \
  --model qwen3.5:9b-mlx --strict-config --sandbox read-only --ephemeral \
  "<bounded prompt>"
```

Run `bash ${CODEX_POLICY_SOURCE}/scripts/validate-codex-exec-runtime.sh`
to inspect the direct lock boundary. A `STATUS: blocked_runtime` result means
the direct environment cannot lock its configured state and is evidence for
using the wrapper fallback; it is not a provider or model failure.

The profile parse check and the Ollama model probe do not replace a real
`codex exec` run. If `codex exec` reports
`failed to initialize in-process app-server client: Operation not permitted`,
the workstation's Codex runtime is blocked before the provider is contacted;
record that as a runtime blocker and do not reinterpret it as a model or
profile failure.

The cloud profile uses `OLLAMA_API_KEY` through the custom `ollama-cloud`
provider configured with Ollama's cloud endpoint. The built-in `ollama` provider
is reserved for the local endpoint and must not be overridden; never put that
secret in a TOML file. Inside Codex, inject it through the checked-in wrapper
and the 1Password Desktop-owned `${HOME}/.codex/.env` FIFO:

```sh
bash ${CODEX_POLICY_SOURCE}/scripts/run-auth-backed.sh \
  --env-file ${HOME}/.codex/.env \
  --require-env OLLAMA_API_KEY \
  -- bash ${CODEX_POLICY_SOURCE}/scripts/run-codex-exec.sh \
  --profile oss-cloud --strict-config --sandbox read-only --ephemeral \
  --model deepseek-v4-flash:0731-cloud \
  "<bounded prompt>"
```

The wrapper is part of the cloud execution contract. It validates that the
canonical path is a non-symlink FIFO owned by the current user with no
group/other access, then lets stable `op` expose values only to the child. Do
not replace it with `env`, direct `op run`, a sourced file, shell-exported key,
or copied secret. Run credential-bearing FIFO stages sequentially through fresh
wrapper invocations; concurrent reads are unsupported. Prove the agent route
with `--env-file ${HOME}/.codex/.env --canary OLLAMA_API_KEY`, which prints only
a fixed result. Keep `--require-environment` as an explicit host beta-XPC route,
not a Codex sandbox bypass. The `oss-local-code`,
`oss-local-fallback`, and `docs` compatibility profiles remain projected
and are validated as explicit readonly lanes; they are not selected by the
primary OSS workflow above.

### Review-waiver contract

Readiness checks and receipts accept full SHA-1 or SHA-256 object IDs. The raw
committed-path parser is tested with real Git repositories in both formats;
isolated provider fixtures cover the complete CLI and receipt validation.
Those fixtures do not prove a hosted provider accepts SHA-256 repositories.

The update-phase readiness waiver is an explicit, short-lived exception for a
solo-maintainer PR when the independent bot reviewers are unavailable. Its
`pr-readiness-review-waiver/v1` record must bind `pr_number`, the full current
`head_sha`, the exact scope, `authorized_by`, `reason`, `rule_or_section`,
`tracking_ticket`, and `expiry_or_adr`. A current-head human `APPROVED` review,
zero unresolved threads, and passing required checks remain mandatory; the
waiver cannot manufacture approval or bypass a `CHANGES_REQUESTED` decision.
Waivers are accepted only by the update phase and are invalid for create or
review-reconciliation phases.

## Policy enforcement baseline

- User/team working rules live in `rules/`.
- `default.rules` holds exact reviewed exceptions only.
- `foundation.rules` provides the read/build/test allowlist without duplicate aliases.
- `guard.rules`, `pr.rules`, and `project.rules` provide prompts/forbids that still apply when the work layer is active.
- `requirements.toml` is the admin-enforced managed-requirements baseline for approval policy, sandbox mode, and MCP server identity constraints.
- Effective command decisions are the most restrictive match across the loaded `.rules` files.

## Git and GitHub capability boundary

Native Git creates commits and 1Password's official
`/Applications/1Password.app/Contents/MacOS/op-ssh-sign` program signs them.
There is no Configs-owned signing broker, LaunchAgent, socket protocol,
repository registry, or alternate Git client. Routine commits use `git commit`
with explicitly owned paths, followed by `git verify-commit HEAD`; Git runs
normal repository hooks and fails closed when 1Password cannot sign. On macOS,
Codex requests the bounded host-capable path for the authorised commit directly
instead of first attempting a signer call from the default sandbox. The stable
FIFO and host-only beta Environment procedures are documented separately in
[`instructions/1Password.md`](instructions/1Password.md).

Amend, hook bypasses, force operations, pushes, and GitHub mutations retain
their independent rules and approval boundaries. PR creation and updates also
require the existing current `pr-readiness/v1` receipt. See
[`docs/adr/0001-native-git-1password-signing.md`](../docs/adr/0001-native-git-1password-signing.md)
and [`instructions/1Password.md`](instructions/1Password.md).

Canonical policy remains under `codex/`. Policy activation requires projection
to `~/.codex`, a Codex restart, and proof from a fresh task. Never edit the
runtime rule or instruction copies as the source of truth.

## Managed configuration rollout

- Use Team Config to distribute shared `config.toml`, `rules/`, and `skills/`.
- Use managed `requirements.toml` for admin-enforced constraints on approvals, sandbox modes, and MCP identity allowlists.
- For a deployment guide and rollout posture, see:
  - `instructions/managed-configuration.md`

## Maintenance launchd jobs

- Repo-managed launchd templates live at:
  - `${CODEX_POLICY_SOURCE}/launchd/*.plist`
- Install/reload jobs:
  - `bash ${CODEX_POLICY_SOURCE}/scripts/install-maintenance-launchd.sh`
  - `bash ${CODEX_POLICY_SOURCE}/scripts/install-maintenance-launchd.sh --dry-run`
- Check status:
  - `bash ${CODEX_POLICY_SOURCE}/scripts/maintenance-launchd-status.sh`
- Managed labels:
  - `com.jamiecraik.mise-tools-updater`
  - `com.jamiecraik.mcp-cleanup`
  - `com.jamiecraik.config-projection-reconciler`
  - `com.jamiecraik.session-collector`

Local Memory is retired. The installer does not register its daemon, and
SessionStart does not run its indexer. Project Brain remains file-based.
The old daemon entrypoint is a no-op so an older installed job cannot restart it.

- `mcp-cleanup` also performs maintenance-health checks on each run:
  - scans `~/Library/Logs/Codex/mcp-watchdog.log` for restart/threshold events,
  - scans `~/Library/Logs/mise/mise-tools-sync.log` for timeout/restart signals,
  - checks for outdated MCP-related mise tools.
- auto-upgrade is enabled in the default launchd template (`MCP_CLEANUP_AUTO_UPGRADE=1`); set to `0` to disable.
  - tune these with optional environment variables in `codex/launchd/com.jamiecraik.mcp-cleanup.plist`:
    - `MCP_CLEANUP_TIMEOUT_WINDOW_MINUTES` (default `120`)
    - `MCP_CLEANUP_TIMEOUT_TOLERANCE` (default `6`)
    - `MCP_CLEANUP_STRICT_HEALTH` (default `0`)
    - `MCP_CLEANUP_MISE_TOOLS` for custom tool set (space/comma-separated)
    - `MCP_CLEANUP_MISE_BIN` to point at a non-standard mise binary
  - for per-machine overrides without editing the repo, create:
    - `~/.config/codex/mcp-cleanup.env` (e.g. `MCP_CLEANUP_AUTO_UPGRADE=0`)
    - or copy the example and edit:
      - `cp ${CODEX_POLICY_SOURCE}/scripts/mcp-cleanup.env.example ~/.config/codex/mcp-cleanup.env`
    - or use the no-upgrade profile:
      - `cp ${CODEX_POLICY_SOURCE}/scripts/mcp-cleanup.no-upgrade.env ~/.config/codex/mcp-cleanup.env`
    - then reinstall launchd: `bash ${CODEX_POLICY_SOURCE}/scripts/install-maintenance-launchd.sh`

- `config-projection-reconciler` continuously reconciles Codex, mise, and terminal symlink projection:
  - canonical template path: `${CODEX_POLICY_SOURCE}/launchd/com.jamiecraik.config-projection-reconciler.plist`
  - canonical script: `${CODEX_POLICY_SOURCE}/scripts/reconcile-config-projection.sh`
  - the repo remains canonical for protected policy while
    `~/.codex/config.toml` remains a mutable Desktop-owned runtime copy
  - runtime drift is repaired from canonical policy; Desktop-owned Computer Use
    plugin consent survives and other runtime-only state remains recoverable in the backup
  - the job watches `~/.codex/config.toml` and also runs every ten minutes
  - plugin cache state is intentionally left under Codex's runtime-owned
    `~/.codex/plugins` directory
  - logs:
    - `${HOME}/Library/Logs/Codex/config-projection-reconciler.log`
    - `${HOME}/Library/Logs/Codex/config-projection-reconciler.err.log`

- `session-collector` refreshes the canonical session evidence artifact used by the daily workflow sweep:
  - canonical template path: `${CODEX_POLICY_SOURCE}/launchd/com.jamiecraik.session-collector.plist`
  - canonical script: `${CODEX_POLICY_SOURCE}/scripts/run-session-collector.sh`
  - canonical output: `${HOME}/.agents/session-collector/session-collector.json`
  - canonical bundle: `${HOME}/.agents/session-collector/`; each hourly
    run refreshes the known default project evidence and contract artifacts as
    well as the summary output
  - collector evidence is an index of process and evidence signals, not
    performance telemetry or delivered-outcome authority
  - freshness gate: `python3 ${CODEX_POLICY_SOURCE}/scripts/daily_sweep_evidence_preflight.py`
  - logs:
    - `${HOME}/Library/Logs/Codex/session-collector.log`
    - `${HOME}/Library/Logs/Codex/session-collector.out.log`
    - `${HOME}/Library/Logs/Codex/session-collector.err.log`

## Verification commands

```bash
# Check projection state without repairing it
bash ${DOTS_CHECKOUT}/scripts/link-configs.sh --check

# Verify ~/.codex symlinks point at this repo
bash ${CODEX_POLICY_SOURCE}/scripts/audit-codex-symlinks.sh

# Verify that live schedules are isolated from the repository
python3 - <<'PY'
from pathlib import Path

runtime = Path('${HOME}/.codex/automations')
if runtime.is_symlink() or not runtime.is_dir():
    raise SystemExit(f'Automation runtime must be an isolated directory: {runtime}')
print(f'OK: isolated automation runtime at {runtime}')
PY

# Validate active configuration, including the named-role retirement policy
python3 ${CODEX_POLICY_SOURCE}/scripts/validate-codex-config.py

# Validate profile/MCP/telemetry governance expectations
python3 ${CODEX_POLICY_SOURCE}/scripts/validate-codex-config.py

# Validate released Codex hook wiring and regression cases
bash ${CODEX_POLICY_SOURCE}/scripts/validate-codex-hooks.sh

# Validate execpolicy regressions and requirements baseline
python3 ${CODEX_POLICY_SOURCE}/scripts/validate-execpolicy-rules.py

# Run repository binary/path preflight before multi-step policy or config work
bash ${CODEX_POLICY_SOURCE}/scripts/codex-preflight.sh

# Run the broader local verification harness
bash ${CODEX_POLICY_SOURCE}/scripts/verify-work.sh --fast

# Evaluate rollout readiness and recovery SLO posture
python3 ${CODEX_POLICY_SOURCE}/scripts/hook-governance/rollout_check.py \
  --inventory ${CODEX_POLICY_SOURCE}/docs/hooks-governance/repo-profile-matrix.json \
  --recovery-slo-hours 24 \
  --out ${CODEX_POLICY_SOURCE}/docs/hooks-governance/rollout-check-report.json
```

Installation and repair are separate, mutating operations. When authorized, use
`bash scripts/install-codex-hooks.sh` from this subtree for hooks or
`bash scripts/link-configs.sh --repair` from the repository root for projections.
Do not run them merely to inspect state. Report generators above also write
their declared output files; preserve unrelated dirty reports.

## Repository layout

- `agents/` - optional report templates, manifest schema, and evidence fixtures; no named-role registry or routing metadata
- `retired-agent-roles/` - historical role prompts retained for reference only; not active runtime configuration
- `automations/` - durable automation routing material and historical artifacts; not live schedules
- `instructions/` - instruction and policy documents
- `launchd/` - LaunchAgent plist templates managed in-repo
- `requirements.toml` - admin-enforced Codex requirements baseline for approval, sandbox, and MCP identity constraints
- `rules/` - guardrail and policy rule files
- `scripts/` - verification and operational helper scripts
  - `scripts/streamdeck/README.md` - Stream Deck workflow script runbook and validation notes
