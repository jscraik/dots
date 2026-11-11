# Jamie Codex Compaction Prompt

Summarise the conversation as an execution handoff for the next turn. Preserve only information that changes safe continuation; use relevant sections, not an exhaustive template.

- Objective, scope, and completion contract: current request, still-active earlier requests, acceptance criteria, remaining work, and stop condition. Parent objective status separately from the status of the current child task.
- Authority and decisions: accepted, proposed, rejected, or superseded choices; active instruction paths; approvals still needed. Newest user steering is subject to active higher-priority instructions and controls.
- Working state: observed cwd, branch, relevant files, running commands, and collision risks. Separate `pre_existing_user_changes:` from `codex_changes:`; omit unobserved metadata.
- Ownership and handoff: create or update the task-local worklog, preserving its
  owner task, canonical checkout, branch/HEAD, owned paths and shared Git
  operations. Record outgoing relinquishment and incoming acceptance only when
  ownership actually transfers; when the same writer continues, preserve
  ownership unchanged. If the outgoing owner is unavailable, reassign only
  with Jamie's explicit authorization and verification that no writer remains.
  Record that decision and the incoming writer's acceptance.
  Carry authorized operations and destinations separately from pending executor approvals.
- Progress checkpoint: last completed command, result and observation time; any running command, blocker and next action. An active task flag alone does not establish progress or authorize a replacement writer.
- Evidence: exact commands and useful results. Use `Command: (cwd=<absolute cwd>) <exact command> -> pass|fail|blocked (<reason>)`. Keep local, runtime, hosted, and review claims distinct.
  Preserve freshness and source where they affect the next action; retain and compress every lane whose state changes the completion claim.
- Blockers and next action: first failed boundary, safe alternatives already tried, unresolved decisions, and one concrete next step with its expected evidence.

Do not invent cwd, branch, files, diffs, validation, command output, or user intent. Label consequential unknowns and inferences. Do not include hidden reasoning, secrets, tokens, credentials, repetitive instructions, routine chatter, or bulky output.

Previous compaction summary: retain decisions, completed work, and blockers that still matter. Do not search session history, rollout logs, hook receipts, or handoff files unless the task requires it or active context is insufficient. After compaction, continue from completed work and the live state.

End with:
`Resume from: <one concrete next command, file edit, validation step, decision point, or unknown>`
