# Agent Testing Gates

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Gate matrix (compact)](#gate-matrix-compact)
- [Manual checks](#manual-checks)
- [Auto checks](#auto-checks)
- [Escalation rule](#escalation-rule)
- [Contradictions and cleanup](#contradictions-and-cleanup)

## Gate matrix (compact)

| Gate | Domain | Type | Owner | Pass condition | Evidence |
| --- | --- | --- | --- | --- | --- |
| G1 | Scope and docs discovery | Auto | Change owner | Applicable `AGENTS.md`, selected references, and edited docs identified | Inspected paths |
| G2 | Validator availability | Auto | Change owner | Required validator dependencies available; discovery fallbacks reported separately | Command output |
| G3 | Link integrity | Auto | Operator | All intra-repo links in touched docs resolve | Validation command output |
| G4 | Selected audit contract | Manual | Named contract owner | Required `09-audit-trail-policy.md` record complete, only when selected | Contract-required record |
| G5 | Security posture | Manual | Change owner | No new secrets; selected security review completed when required | Findings and verification |
| G6 | Governance coherence | Manual | Change owner | Touched guidance agrees with its active authority and executable consumers | Diff and focused proof |
| G7 | Subagent artifact contract | Auto | Coordinator | Retained templates, manifest schema, eval fixtures, and explicitly supplied artifacts validate without a role registry | `python3 scripts/validate-agent-artifacts.py` output |

## Manual checks

- Verify each new governance doc has a correct TOC heading.
- For a selected audit contract, verify the named participants and their actual
  authority. Ordinary local edits require no proposer/reviewer/approver ceremony.
- Record unavailable validator dependencies separately from safe discovery fallbacks.

## Auto checks

- Dots CircleCI defines `validate` and `secret-scan` in
  [its configuration](../../../.circleci/config.yml). Validation checks provenance,
  Python style, guidance, the full fixture suite with the pinned Linux CLI, and
  shell syntax. The separate job scans committed history and checked-out files.
  No dots `pnpm check`, typecheck job or source-only CI graph test is implied.
  Hosted execution and required branch protection must be inspected separately.

- Ordinary child returns require no artifact. The coordinator owns durable
  records unless it explicitly assigns an artifact deliverable to a child.
- Check commands required by the affected validator, using the repository's
  documented runtime. Do not impose a preferred-tool installation gate.
- Verify no stale links from touched docs and root map files.
- Verify changed references resolve through their relevant routing index; do not
  add every optional document to the global instruction chain.
- Verify explicit artifact contracts with `python3 scripts/validate-agent-artifacts.py`; this checks templates, structured receipts, manifest schema and eval fixtures without requiring role registrations or child-authored files.
- Verify the aggregate lane includes the artifact contract: `bash scripts/verify-work.sh --fast` must report `agent-artifact-contract-validation` as passed or explicitly blocked.

## Escalation rule

- A failed required release gate blocks release handoff, not independent local
  diagnosis or correction. Optional or unselected lanes cannot establish a new gate.
- `Conditional` status is permitted only with explicit scope and re-check condition.

## Contradictions and cleanup

- Do not call a fallback a passing automated gate. Report the actual available
  evidence and remaining acceptance boundary.
- Delete duplicate gate entries if another source already defines the same gate with the same acceptance criteria.
