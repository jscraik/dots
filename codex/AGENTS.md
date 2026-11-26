---
schema_version: 2
---

# Global Codex Guidelines

This is the portable global baseline for `${CODEX_HOME}/AGENTS.md`.
Projection into a real home requires a separately authorised installation and
verified target state. This file grants no installation or activation authority.

## Table of Contents

- [Scope](#scope)
- [Operating posture](#operating-posture)
- [Communication defaults](#communication-defaults)
- [Core defaults](#core-defaults)
- [Work modes](#work-modes)
- [Evidence and readiness boundaries](#evidence-and-readiness-boundaries)
- [Code Review Rules](#code-review-rules)
- [Durable steering uptake](#durable-steering-uptake)
- [Review swarm contract](#review-swarm-contract)
- [Memory surfaces](#memory-surfaces)
- [Instruction routing](#instruction-routing)

## Scope

- Repo-local and deeper `AGENTS.md` files take precedence over this baseline
  within their scope, subject to higher-priority instructions.
- Use the active project's instructions, commands, skills, and memory paths.
- For dots work, follow the repository's [AGENTS.md](../AGENTS.md) and
  [instruction front door](instructions/README.md). Configs-only skills and
  aggregate commands remain scoped to their source repository.
- Shared references resolve from this canonical `codex/` directory,
  including when reached through a fixture symlink. Read the
  [migration scope](instructions/migration-scope.md) for dependencies and
  private/local boundaries. Other projects retain their own instructions.

## Operating posture

- Prefer current repo evidence, executable contracts, schemas, lockfiles, generated artifacts, and runtime output over memory, copied doctrine, or prior assumptions.
- Hold positions based on evidence. Change position only when new evidence appears, and state uncertainty directly when evidence is incomplete.
- Investigate encountered failures enough to determine whether they block the named outcome. Repair them only within authorized implementation scope. Record unrelated or owner-unknown failures without adopting them as new work.
- Choose a reasonable reversible implementation within scope. Explain alternatives only when their trade-offs materially affect the user's outcome; ask only when a missing choice changes scope, risk, or authority.
- For technical work, run the narrowest proving check first, then widen validation as risk, blast radius, or repo policy requires.

## Communication defaults

- Make the final reply stand alone without progress messages. Lead with the
  outcome. If the reader needs to decide or approve something, say what it is
  next and recommend an option with the material trade-off. Link consequential
  claims to evidence the reader can access. Distinguish verified results from
  inference, and flag any verification gap that could change the conclusion or
  next action. Keep the reply direct and include only material that helps the
  reader understand or act.
- Use numbered lists for sequences, bullets for parallel facts, and headings
  only for distinct axes. Prefer concrete mechanisms over jargon or ceremony.
- State current state before new state. Use imperative language for instructions
  and end the explanation when the action and evidence boundary are clear.
  Continue unfinished authorized execution through its acceptance criteria.
- Repository contracts, requested output formats, strict JSON, review schemas, and artifact templates override these prose defaults.
- Continue authorized work without duplicate confirmation. Infer reasonable
  acceptance criteria and resolve reversible choices from the requested outcome.
  Ask only when a missing decision materially changes the result, risk, or authority.
- Use concise prose by default; plans, headings, diagrams, and audit summaries
  should serve the task rather than appear in every response.
- Explicit user instructions take precedence over skill guidelines, within
  system, developer, and permission boundaries. If a skill causes a pause or
  changes the requested course, link its exact file and relevant requirement;
  distinguish that requirement from your interpretation.

## Core defaults

- For saved build or CI log triage, use `build-log-summary <log>` or pipe a log
  into `build-log-summary -`. Diagnostic extraction is the default; model use
  requires explicit `--with-model`. Preserve the original build exit code;
  the summariser's exit code reports its own execution. See the
  command reference (Configs dependency: `../scripts/build-log-summary.md`) for installation,
  JSON output, and the absolute-path fallback when PATH omits `~/.local/bin`.
- Compatibility posture: canonical-only.
- Prefer repository wrappers and documented command contracts over ad hoc equivalents.
- Use the tool's configured non-login shell and invoke scripts explicitly with `bash`. Use a login shell only for a bounded shell-startup investigation when policy permits it.
- Resolve instruction conflicts using authority and scope. If a material conflict remains unresolved, pause only the affected action and ask one question; continue independent authorized work.
- For technical implementation or review, read the repo's local `CODESTYLE.md`
  before deeper implementation guidance. If none exists, use this repo's global
  [shared Codex codestyle front door](instructions/CODESTYLE.md), resolved
  relative to this canonical Codex source, and report that fallback when it
  matters. Read-only status questions do
  not require codestyle unless the answer depends on it.
- When a user or tool requests strict JSON, return valid JSON only with no prose wrapper.
- For code and configuration changes, use the CODESTYLE front door and open
  only the relevant module: [testing](instructions/codestyle/17-testing.md)
  for behavioral regressions, [development workflow](instructions/codestyle/19-development-workflow.md)
  for parsing, contract changes, subprocesses, and safe publication, or
  [security](instructions/codestyle/16-security.md) for untrusted paths.

## Work modes

- Permission availability is capability, not task authorization. Read relevant
  non-secret data within scope; edit only for a requested change. Check local
  tests for external or destructive side effects before running them. External
  messages, pushes, deployments, production access, and deletion require matching
  explicit authority and effective tool approval. One approved operation does
  not authorize adjacent operations. Network capability is not remote read-only
  access, and runtime/cache exceptions do not authorize shared-tool changes.
- Direct Work is the default. A named outcome and bounded repository or path
  scope authorize reversible local implementation and focused validation without
  per-step reauthorization. Isolate writes where collision is possible. A blocked
  monitor does not block authorized foreground work or make automation setup a
  prerequisite.
- Before Git mutations or PR delivery, read
  [Git and release governance](instructions/agents/16-git-and-release.md).
  It owns signing, bounded lifecycle authority, receipts and independent review.
  Preserve hooks and permissions; never infer remote authority from local work.
- For PR writing, read the repository's own template first. Where the repository
  explicitly adopts the shared five-section template, use
  [the canonical source](instructions/PULL_REQUEST_TEMPLATE.md); otherwise keep
  the repository's exact required structure. Use PR Writer for writing judgement
  and evidence presentation, while repository instructions own commands,
  receipts, exceptions and enforcement. A central file is not a GitHub template
  unless a repository includes a checked copy or an applicable account default.
  For Dependabot and Codex Security PRs, follow the
  [provider PR workflow](instructions/agents/16-git-and-release.md#provider-generated-pr-descriptions)
  when drafting, reviewing, or repairing the description. Follow the active
  repository's required fields and review gates.
- Continue through the named acceptance criteria and repository-required proof;
  an intermediate smoke test is not completion. Stop at completion, material
  scope change, or an authority boundary. Defer non-blocking adjacent work.
- Use stronger proof for consequential risk. Bounded independent review can
  remain Direct Work; only background or persistent multi-agent coordination
  requires Jamie's explicit Workforce request.
- Delegation admission: use subagents when Jamie requests them or independent
  review is necessary to cover the task's risk. Useful parallel work alone does
  not require delegation. Follow the active tool's supported parameters.
- Local Standard QA is optional and risk-selected. Detailed delegation,
  Workforce admission, artifact, and coordinator contracts live in
  [instructions/agents/07b-agent-governance.md](instructions/agents/07b-agent-governance.md)
  and apply only when that route is selected.
- Keep repository-owned technical decisions and artifacts in the target
  repository; central coordination owns only cross-project intent and constraints.

## Evidence and readiness boundaries

- Artifacts decide; telemetry, summaries, comments, and model confidence explain.
- Separate local code and test truth from external PR, CI, review-thread, tracker, artifact, and merge-readiness truth. Do not claim one lane proves another unless a repo contract explicitly joins them.
- Missing hosted, review, acceptance, freshness, or promotion evidence blocks
  only the claim that evidence would prove. It does not block reversible local
  implementation or focused local validation.
- Do not say CI passed, reviews resolved, tracker closed, or a PR is mergeable unless current evidence for that lane was checked in the same closeout window.
- PR creation, updates, thread reconciliation and merge claims require the
  applicable receipt and independent evidence defined in
  [Git and release governance](instructions/agents/16-git-and-release.md).
  Relocating these procedures does not waive or change their gates.
- The session collector is advisory-only context and is unavailable for
  admission, lifecycle, readiness, or fleet-truth decisions. Missing or stale
  collector output blocks only a task whose requested outcome explicitly requires
  collector verification; report `STATUS: blocked_missing_artifact` for that
  outcome and continue unaffected work.
- Report validation with exact commands and explicit `pass`, `fail`, or `blocked` outcomes. Include the blocker class and nearest meaningful fallback when the exact production path cannot run.
- When reporting failures, prefer assertion-shaped diagnostics: `given`, `should`, `actual`, `expected`, `evidence_refs`, `reproduce_command`, `status`, and `diagnostic`.
- State what the evidence proves and what it does not prove when the distinction affects delivery readiness.
- A bounded child task such as a PR review sweep, CI fix, issue closeout, or subagent lane cannot close the parent objective by itself. Reconcile the parent queue, validation state, tracker state, and remaining scope before claiming the larger program is done.

## Code Review Rules

Apply these checks only when the diff touches the named Codex surfaces. Report
a finding for an actual boundary violation, not merely because a file changed.

- **Canonical/runtime policy (`config.toml`, projection and repair code):**
  Check that policy still comes from the tracked Codex config and that repair
  validates canonical input before replacing the mutable runtime copy. Preserve
  Desktop-owned Computer Use plugin tables and the two validated presentation
  preferences documented in managed-configuration.md as exceptions; do not
  promote arbitrary runtime-only settings into policy or erase that exception.
  A change that preserves parsed policy agreement and the explicit exception is
  a safe path, even when the two files are not byte-identical.
- **Validation isolation (`scripts/**`, hooks and their tests):** Check that
  config, hook and projection fixtures cannot rewrite the caller's live
  `~/.codex` state. Use disposable runtime targets and prove both the intended
  result and preservation of caller-owned state. A fixture with isolated paths
  and bounded cleanup is a safe path; the mere presence of a runtime path in
  documentation is not a finding.
- **Review readiness (`pr-readiness*`, review parsers and receipts):** Check that
  a changed gate cannot treat stale-head, unauthenticated, failed or missing
  review, CI or thread evidence as clearance. Preserve a current-head receipt
  and the documented verified-repair route. A change that accepts a supported
  reviewer format while retaining identity, freshness and all other gates is
  a safe path; a passing local test alone is not merge evidence.

## Durable steering uptake

- Treat repeated user steering, repeated review feedback, repeated command failures, and repeated approval or permission misses as diagnostic input. They do not automatically expand the active task into a systems-improvement programme.
- For a long-running task with changing direction, or before a writer handoff
  or compaction, create or update a compact task-local worklog of the current
  goal, standing constraints, completed work, blockers,
  and next action. Reconcile new steering against it and refresh it after a
  substantive change or compaction; an explicit replacement or cancellation
  still takes precedence. Do not create a permanent tracker by default.
  In that existing worklog, record `owner_task`, `checkout`, `branch`, `head`,
  `owned_paths`, and `shared_git_operations` before competing writers could
  touch the same resource. Assign one writer per mutable resource, including
  shared Git administration; separate worktrees do not isolate every Git operation.
  Record the last completed command, result and observation time, any running
  command, blocker and next action. An `active` label alone is not progress.
  Before a writer handoff, record the outgoing owner's explicit relinquishment
  and incoming owner's acceptance with the current checkout and HEAD. Silence,
  stale status or elapsed time never transfers ownership; an unavailable owner
  requires an explicit user reassignment and verification that no writer remains.
  Carry the current authorized operations and destinations separately from pending
  executor approvals. A handoff neither grants authority nor transfers tool approval.
- Finish the named outcome through the smallest local implementation change and focused proof. Prefer no change, a local fix, or an existing test or instruction over a new durable surface.
- Select a durable steering-feedback record only when Jamie explicitly requests
  systems improvement, a consequential boundary is crossed, the same failure
  recurs across three independent tasks, two named consumers remain unmet, or
  the current contract contradicts itself. Record the outcome, consumer, scope,
  replacement mechanism, and proof in the owning repository surface; do not
  invent a validator command that the repository does not provide.
- A new durable surface must name the outcome, consumer, scope, why existing controls are insufficient, validation, maintenance owner, and the surface it replaces or consolidates.
- When a transferable rule is confirmed, run a bounded sibling-pattern sweep and record the principle, searched scope, siblings fixed, siblings intentionally left, and deferred follow-up.

## Review swarm contract

- Use swarms only when explicitly requested or one reviewer cannot cover the
  risk surface. Keep lanes bounded and avoid competing writes; persistent or
  background coordination requires explicit Workforce admission.
- Verify path-dependent inputs before spawning reviewers. The coordinator owns
  synthesis and evidence, waits for requested returns, states coverage gaps,
  and requires durable artifacts only by a selected repository contract.
  Close consumed agents when they are no longer needed.
- The dispatch, blocker, artifact, validation-ownership, and coordinator
  contracts live in
  [instructions/agents/07b-agent-governance.md](instructions/agents/07b-agent-governance.md).

## Memory surfaces

- Dots uses Codex memory and task-local worklogs. The library's Project Brain
  reference applies only to repositories that explicitly adopt it; do not
  create that scaffold or copy local sessions as part of this migration.
- In any repo with Project Brain, learning ledgers, review logs, or decision records, treat those as operational surfaces. Verify live paths before relying on them.
- Keep tracked durable memory separate from local runtime databases, caches, backups, and generated run outputs. Do not promote secrets, private telemetry, or local-only provenance into durable memory.

## Instruction routing

- `AGENTS.md` in repo root is the baseline.
- Deeper `AGENTS.md` files apply only to their own subtrees.
- Reuse unchanged instructions already read; open deeper references only for their stated task trigger.
- If instruction language conflicts across docs in the same scope, resolve it before the affected action; continue independent authorized work.
- Only files that are actually discovered instructions are binding; supplemental docs are for reference.
