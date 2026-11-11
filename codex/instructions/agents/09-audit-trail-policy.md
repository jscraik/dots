# Audit Trail Policy

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Approval record requirement](#approval-record-requirement)
- [Compact templates](#compact-template)
- [Who approved what](#who-approved-what)
- [Per-change examples](#per-change-examples)
- [Agent-Run Provenance Policy](#agent-run-provenance-policy)
- [Contradictions and cleanup](#contradictions-and-cleanup)

## Approval record requirement

- For an explicitly selected audit or release-control workflow, include an audit record that identifies:
  - proposer
  - reviewer
  - approver(s)
  - exact scope approved
  - evidence source
  - effective date/time (UTC)

## Compact template

Ordinary Direct Work documentation changes use the diff, validation evidence,
and any requested PR record. They do not require a separate approver ceremony.
The template below applies only to a selected audit or release-control workflow.

- Append at the top of the relevant change note / PR summary:

```md
- Change ID: `<id>`
- Title: `<short summary>`
- File scope: `<paths>`
- Proposed by: `<name/handle> · <UTC ISO timestamp>`
- Reviewed by: `<name/handle> · <UTC ISO timestamp> · <review method>`
- Approved by: `<name/handle, role> · <UTC ISO timestamp>`
- Approval model: `single-owner` | `dual-owner`
- Approved what: `<enumerate exact sections/lines or headings>`
- Approved conditions: `<explicit conditions and constraints>`
- Evidence: `<command output / file hash / screenshot link>`
- Revert plan: `<who can revert + what to revert>`
- Status: `approved` | `conditional` | `deferred`
```

## Who approved what

- **Approved what** must be explicit and granular.
- If one change contains mixed scope, list per-scope entries (for example, one for `AGENTS.md` and one for `instructions/agents/08-...`).
- If approval is conditional, list each unmet condition and the trigger for final approval.

## Per-change examples

- **Doc clarification:** allowed with same approver scope and one explicit reviewer.
- **Security policy update:** requires reviewer + approver with security authority.
- **Role/authority update:** requires approver role with policy authority and explicit dual-owner if high-risk.

## Agent-Run Provenance Policy

This section applies only when the selected artifact contract explicitly requires
agent-run provenance. Follow [07b-agent-governance.md](./07b-agent-governance.md)
for ordinary returns; these controls do not create an artifact or Local Memory
prerequisite for Direct Work.

- Scope: `artifacts/agent-runs/*/manifest.json` entries with `repo.repository`, `repo.branch`, and `repo.headSha`.
- The coordinator writes these records by default, retaining the child's identity
  and evidence attribution. A role name alone does not delegate artifact ownership.
- Schema: every subagent manifest must conform to `agents/schemas/agent-run-manifest.schema.json` and must be referenced by the subagent artifact `manifest_path` field.
- `manifest_path` is relative to the validator's `--root` and must name a
  nonempty regular file. Absolute paths, parent traversal, symlink components
  and special files are rejected; inspection stays bound to opened directories.
- New runs use `complete`, `blocked_runtime`, `blocked_missing_artifact`, `blocked_validation`, or `failed_artifact_validation`. Local Memory is retired and cannot block a new run.
  Existing artifact schemas and readers retain `blocked_local_memory_cli` only to read historical receipts; do not emit it or restart the retired service.
- Historical Local Memory evidence remains historical; the retired service is not required for new provenance.
- Coordinators that spawn agents must preserve a ledger using `agents/templates/coordinator-ledger.md` when more than one role is requested or when any role blocks.
- `unknown` provenance is acceptable only for early-failure remediation runs where:
  - `outcome = "failed"`, and
  - `exit.classification = "validation_failed"`, and
  - `provenance.unknownProvenanceReason` explains why repository metadata could not be captured.
- Failed runs with unknown provenance may be committed to VCS only as temporary forensic artifacts when they include:
  - current `contract.hash` and `provenance.repoContractHash` matching `harness.contract.json`,
  - an explicit unknown-provenance reason in the manifest, and
  - a follow-up remediation note in commit/PR text.
- An unchanged, previously committed failed validation record may retain its
  historical hashes when the validator verifies its exact bytes and both hashes
  against `harness.contract.json` at the last commit that changed that record.
  Missing history or a mismatched witness fails closed. This permits forensic
  retention only: it is not current-contract, successful-run or readiness evidence.
  New or modified records and successful evidence still require current hashes.
- Update or remove conditions:
  - If exact provenance becomes available (`repository`, `branch`, `headSha`), replace `unknown` values on the next artifact refresh.
  - If the run is superseded by a successful rerun, remove the stale failed artifact in the same change that adds the replacement evidence.
  - Retain unresolved failed artifacts only while actively triaging; remove once remediation is complete.
- Remediation workflow for replacing unknown provenance:
  1. Capture real repo metadata (`repository`, `branch`, `headSha`) from the run environment.
  2. Recompute and align `contract.hash` and `provenance.repoContractHash` with current `harness.contract.json`.
  3. Regenerate or normalize the manifest so JSON ends with a trailing newline.
  4. Commit the refreshed artifact with a short audit note describing why unknown provenance was replaced or why the failed run was removed.

## Contradictions and cleanup

- Resolve apparent conflicts using active instruction precedence, scope, and the
  selected contract. Ask only when applicable live requirements remain incompatible.
- If prior edits only include “approved by” in changelog prose, replace with this compact template.
