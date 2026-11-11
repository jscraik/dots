# Managed Codex Configuration

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Use this guide when you want to move from a strong local setup to a genuinely enterprise-grade Codex rollout with admin-enforced controls.

## Table of Contents

- [Why this matters](#why-this-matters)
- [Current repo layering model](#current-repo-layering-model)
- [Canonical config doctrine](#canonical-config-doctrine)
- [Projection write boundary](#projection-write-boundary)
- [Managed hook manifest](#managed-hook-manifest)
- [Admin-enforced requirement layers](#admin-enforced-requirement-layers)
- [Recommended rollout posture](#recommended-rollout-posture)
- [Enterprise pins to consider before rollout](#enterprise-pins-to-consider-before-rollout)
- [Telemetry and privacy baseline](#telemetry-and-privacy-baseline)
- [Harness engineering checklist](#harness-engineering-checklist)
- [Suggested deployment flow](#suggested-deployment-flow)
- [Reference](#reference)

## Why this matters

This repository uses `requirements.toml` as the admin-enforced layer for
approval policy, sandbox mode, and MCP server identity constraints. Confirm
current vendor behavior from official documentation before changing the
distribution model for shared defaults, rules, or skills.

That means a gold-standard setup should separate:

- **working defaults** in `config.toml`
- **team/user workflow rules** in `rules/`
- **non-negotiable config constraints** in `requirements.toml`
- **deployment and governance** in Team Config / managed configuration

## Current repo layering model

This repo already follows the correct direction of travel:

- `config.toml` sets safe interactive defaults.
- `~/.codex/config.toml` is a regular mutable runtime copy of the tracked root `config.toml`.
- `rules/` contains the working command-governance layers.
- `requirements.toml` is constraint-only and suitable for managed rollout.
- `scripts/validate-execpolicy-rules.py` provides policy regression coverage.
- `scripts/codex-preflight.sh` and `scripts/verify-work.sh` provide harness gates before broader changes.

## Canonical config doctrine

For this workstation, the tracked repo file is the only canonical Codex config:

- `${CODEX_POLICY_SOURCE}/config.toml` is the source of truth.
- `${CODEX_HOME}/config.toml` is an isolated regular runtime copy.
  Its parsed policy must match the canonical file after reconciliation, except
  that Desktop-owned Computer Use plugin tables retain their live installation
  and consent state. Other Desktop writes can introduce drift without changing
  the source; they are not a second policy source.

Enforcement rules:

- Do not treat the runtime copy as a second policy source; policy changes belong in the tracked root file.
- Do not recreate repo-local `.codex/config.toml`; the home-layer runtime copy is the supported main-config projection.
- Profiles, hooks, rules, and other mapped entries remain symlinked or copied according to `codex/projection-map.json`. Standalone skills are installed by their provider, not projected by Configs; the reconciler archives only recognised former Configs-owned skills aliases.
- If the retired skills alias used a custom `SKILLS_CANON`, supply that same override during migration. An unrecognised skills symlink is left untouched for manual ownership review.
- Any policy drift fix must update the tracked root file first, then use the projection reconciler for the affected target.
- `scripts/codex-preflight.sh` and `scripts/validate-codex-config.py` are the enforcement gates for this doctrine.

## Projection write boundary

`~/.codex/config.toml` is a mutable runtime copy, deliberately separated from
the tracked policy source. The ChatGPT desktop app, Codex CLI, and IDE
integrations share the Codex home configuration layer, so an in-app
configuration edit can update generated runtime settings without changing the
reviewed repository policy.

Treat the tracked file as the edit surface and reconcile the home copy from it:

- Make intentional edits in `${CODEX_POLICY_SOURCE}/config.toml`.
- Keep `${CODEX_HOME}/config.toml` a regular file. The `copy-runtime`
  projection strategy checks parsed policy agreement while preserving Desktop-owned
  Computer Use plugin tables and two validated presentation preferences:
  `model_verbosity` (`low`, `medium`, `high`) and `model_reasoning_summary`
  (`auto`, `concise`, `detailed`, `none`). Absence selects the model default.
  These runtime choices are never copied back into canonical policy. Model,
  approvals, permissions, network policy and all other settings remain canonical.
  Invalid presentation values block replacement rather than being preserved.
  When policy drifts, repair replaces the regular
  file with validated canonical content plus those Desktop-owned settings after
  saving a private backup; it removes other runtime-only settings and comments.
  Full canonical publication first runs the repository config validator against
  the captured snapshot via `--config-stdin`. Invalid policy or unavailable
  validation resources block before backup creation or runtime publication.
  Snapshot mode retains canonical policy and resource checks, but excludes the
  existing home projection and other installed project configurations. The normal
  validator invocation still checks those separately, so repairable runtime drift
  cannot veto a valid replacement candidate.
  Snapshot policy rejection exits with status 65 and retains bounded policy
  diagnostics. Inaccessible required marketplace or schema resources exit 69.
  Resource and execution failures are reported as `canonical_validation_unavailable`
  with bounded validator output rather than `canonical_source_invalid`.
  Changes observed before publication abort replacement. If verification fails after the atomic
  exchange, repair reports failure, leaves the runtime path untouched, and
  reports the displaced version's recovery path. It does not automatically
  roll back over a potentially newer Desktop write. Inspect both files before
  retrying; policy agreement is not established on this failure path.
  Missing or symlinked targets are restored
  through the projection reconciler.
- Session-start maintenance invokes the same repair helper in its default
  `repair` mode. Set `CODEX_SESSION_REPAIR_MODE=check` for detection without
  replacement; invalid modes remain check-only and symlink targets are rejected.
- Do not use a settings editor or profile migration to write legacy root
  `sandbox_mode` or `[sandbox_workspace_write]` keys. The active contract is
  `default_permissions` plus the named `permissions.<profile>` tables.
- If either legacy key reappears, classify it as projection drift, remove it
  from the canonical file, and run `python3 codex/scripts/validate-codex-config.py`
  before trusting the next session.

The projection reconciler creates or checks the runtime copy and the remaining
symlink projections; it must never be treated as proof that the source file is
contract-valid. A successful projection check proves target shape and path
ownership and parsed policy agreement (excluding valid Desktop presentation
preferences and Desktop-owned Computer Use plugin consent), while the config
validator proves the schema and permission
contract separately. Agreement is a point-in-time check,
not a guarantee that a running app cannot subsequently write new drift.

## Managed hook manifest

`~/.codex/hooks.json` is a regular copy of `codex/hooks/hooks.json`; the hook
scripts directory remains a symlink. The owning policy checkout remains
authoritative. Reviewed integration additions belong in its canonical manifest
before reconciliation. During this migration, Configs remains that live owner.

`project-codex-hooks.py` validates the manifest, publishes it atomically and
retains the displaced runtime file or link as a private recovery path. Checks
require identical canonical bytes; unreviewed runtime additions are not retained.
The dots port admits only disposable fixtures and rejects live installation.

Approved Braid definitions are validated separately from the existing guard
definitions. Capture, consent and uploading are distinct authority boundaries.
Review generated definitions after an upgrade; never automatically grant trust
hashes or copy a machine's consent state into the public repository. CLI
discovery alone does not prove Desktop lifecycle capture.

## Admin-enforced requirement layers

Official Codex managed-configuration guidance says requirements are applied in this order:

1. cloud-managed requirements for ChatGPT Business / Enterprise
2. macOS managed preferences via `com.openai.codex:requirements_toml_base64`
3. system `/etc/codex/requirements.toml`

Across those layers, earlier fields win. Later layers can only fill fields that remain unset.

Practical implication:

- Put **org-wide non-negotiables** in the earliest managed layer you control.
- Keep local `requirements.toml` aligned with that managed policy so drift is obvious during review.
- Use separate managed groups when you need stricter defaults for most users but narrower exceptions for power users, CI, or isolated environments.

## Recommended rollout posture

For a modern Codex fleet, the default target should be:

- approvals constrained to reviewed modes
- sandbox constrained to `read-only` or `workspace-write` by default
- exact destructive command prompts/forbids enforced via managed `.rules` files
- MCP servers allowlisted by identity where feasible
- telemetry exported only to collectors you control
- prompt contents excluded from telemetry unless policy explicitly permits collection

This repo intentionally keeps some stronger controls as **documented rollout recommendations** rather than forcing them locally, because local power-user and automation scenarios may still need carefully scoped exceptions.

## Enterprise pins to consider before rollout

These are the main additional managed controls worth evaluating before wider deployment:

### 1. Approval policy pins

Consider:

```toml
allowed_approval_policies = ["on-request"]
```

Why:

- this removes unattended mutation by default
- it aligns with the official managed-config example posture

Tradeoff:

- it would block local `automation-patch` style flows unless you create a separate managed group or isolated environment policy

### 2. Sandbox mode pins

Consider:

```toml
allowed_sandbox_modes = ["read-only", "workspace-write"]
```

Why:

- it removes `danger-full-access` from normal workstation use
- it keeps escalation inside safer, reviewable boundaries

Tradeoff:

- any profile requesting `danger-full-access` would be rejected by that
  managed layer
- if you still need `danger-full-access`, isolate it to dedicated machines, containers, or a separate managed group

### 3. MCP identity allowlisting

Consider adding managed `mcp_servers` allowlists once you have a stable inventory of approved servers and identities.

Why:

- official managed-config guidance allows Codex to enable an MCP server only when both the name and identity match an approved entry
- this is the strongest control for preventing silent drift in local tool exposure

Tradeoff:

- this requires disciplined MCP inventory management
- a stale allowlist can accidentally disable legitimate workflows

## Telemetry and privacy baseline

Official Codex security guidance supports the following posture:

- keep `log_user_prompt = false`
- route telemetry only to collectors you control
- treat tool arguments and outputs as sensitive
- review approval/sandbox changes and unexpected tool executions periodically
- align transcript retention with policy and storage expectations

This repo already has `log_user_prompt = false` in `config.toml`. Keep it that way unless you have an explicit policy reason to change it.

## Harness engineering checklist

Gold-standard harness engineering for this repo should now look like:

1. **preflight first**
   - `bash scripts/codex-preflight.sh`
2. **policy regression second**
   - `python3 scripts/validate-execpolicy-rules.py`
3. **broader repo verification third**
   - `bash scripts/verify-work.sh --fast`
4. **manual spot checks for risky edits**
   - `codex execpolicy check --pretty ...`
5. **operational rehearsal**
   - run simulated incident or approval-path scenarios for any major policy shift

That sequence reflects the current OpenAI guidance to connect AI tools to logging/deployment systems, define access scopes, use reusable prompts, and test workflows with simulated incident scenarios.

## Suggested deployment flow

1. Keep editing policy in this repo first.
2. Validate locally with:
   - `bash scripts/codex-preflight.sh`
   - `python3 scripts/validate-execpolicy-rules.py`
   - `bash scripts/verify-work.sh --fast`
3. Promote approval, sandbox, and MCP identity constraints into managed `requirements.toml`; promote command policy through the managed `rules/` distribution.
4. Roll out by group:
   - baseline users
   - power users
   - CI / isolated automation
5. Review telemetry and approval-path behavior after rollout.
6. Tighten pins only after you have evidence that the stricter posture does not break required workflows.

## Reference

- `README.md`
- `requirements.toml`
- `scripts/codex-preflight.sh`
- `scripts/validate-execpolicy-rules.py`
- `scripts/verify-work.sh`
- `instructions/work-rules.md`
