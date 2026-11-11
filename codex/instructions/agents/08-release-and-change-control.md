# Release and Change-Control Checks

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Change classification](#change-classification)
- [Pre-change controls](#pre-change-controls)
- [Post-change controls](#post-change-controls)
- [Execpolicy Mutation Constraints](#execpolicy-mutation-constraints)
- [Release handoff checklist](#release-handoff-checklist)

## Change classification

- **Doc-only edits**: updates to AGENTS, category docs, or `codex/FORJAMIE.md`.
- **Governance edits**: policy, approvals, role definitions, testing gates.
- **Process edits**: checks, automation instructions, workflows.

## Pre-change controls

- Run discovery and verification before edits.
- Check the tools actually required by the selected validation lane.
- Verify referenced files exist before writing links.
- Use [07a-role-governance.md](./07a-role-governance.md) for selected independent
  review and [07b-agent-governance.md](./07b-agent-governance.md) for admitted
  delegation; neither creates a role prerequisite for Direct Work.

## Post-change controls

- Confirm TOC remains accurate in any edited doc.
- Confirm new links are resolvable from root `AGENTS.md` and `01-instruction-map.md`.
- Record a separate audit block only when the selected audit/release contract
  requires it; otherwise the diff, validation evidence, and requested PR record
  describe the change.
- Ensure no duplicated policy statements remain un-pruned.

## Execpolicy Mutation Constraints

- Any `prefix_rule` that performs git state mutation (`push`, `checkout -b`, `rebase`, broad `git add`) must default to `decision="prompt"` unless the command is fully path-scoped and explicitly reviewed.
- Auto-trust commands for external or temporary config files (for example `mise trust` on `/tmp/*`) must be `decision="forbidden"` unless provenance verification is performed in a separate, approved workflow step.
- Git-affecting `prefix_rule` changes must rely on an equivalent guard path:
  - explicit operator prompt (`decision="prompt"`), and
  - active `PreToolUse` shell guard enforcement (`codex/hooks/pre-tool-use-guard.sh`) at runtime.
- Release handoff must call out any new or changed mutating `prefix_rule` entries and why they are safe.

## Release handoff checklist

- Preserve the actual authorization scope; include named approval records when
  required by the selected release contract.
- Confirm if manual gates are required and completed.
- If `AGENTS.md` or `codex/instructions/**` changed durable Jamie guidance, update `codex/FORJAMIE.md` the same day before closeout and mention the changed files.
- Archive any temporary branch notes in `codex/FORJAMIE.md` if the change was cross-session critical.
