# Bounded Subagent Governance

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [When to delegate](#when-to-delegate)
- [Dispatch contract](#dispatch-contract)
- [Artifact contracts](#artifact-contracts)
- [Coordinator closeout](#coordinator-closeout)

## When to delegate

Follow the delegation admission rule in [AGENTS.md](../../AGENTS.md).
Admitted lanes must avoid competing for the same files, state, or decision. Keep Direct Work
single-threaded by default. Bounded independent delegation and a risk-selected
review swarm are Direct Work QA outside Workforce; only persistent or
background multi-agent coordination requires explicit Workforce admission.
The session collector is advisory context only and never an admission,
readiness, or lifecycle gate.

## Dispatch contract

Before dispatching, verify the target path and give the subagent a bounded
outcome, authority, and return format. Do not assume a role registry, a hidden
Desktop feature flag, or target-repository commands exist. A task that needs
live repository context should run the repository's documented discovery and
validation commands rather than generic controller commands.

Before a writer handoff, create or update the task-local worklog using the
ownership and checkpoint fields from [the global baseline](../../AGENTS.md#durable-steering-uptake).
Name the single writer for each path and shared Git operation. Record explicit
relinquishment and acceptance when ownership transfers. If the outgoing writer
is unavailable, do not reassign ownership solely because no writer appears
active: proceed only after Jamie explicitly authorizes reassignment, verify that
no writer remains active, and record the decision and incoming writer's
acceptance. A stalled or silent task alone does not release ownership.
Carry current authorization separately from executor approvals, and verify the
checkout and HEAD before continuing. Read-only reviewers own no mutations.

Each return must identify the candidate/base, result, findings or blocker,
command evidence, and what the evidence does and does not prove. A blocker
uses one of `blocked_runtime`, `blocked_missing_artifact`,
or `blocked_validation` with the exact failure and
next action.

Delegate a concrete task whose inputs, files, output, and proof can all be
stated in the dispatch. Inherit the coordinator's model and context by default.
Override model, reasoning effort, or fork depth only when the user, the selected
contract, or the task's bounded needs justify it and the active tool supports
those parameters. Do not invent tool parameters or assign a worker peer
coordination without explicit authority.

## Artifact contracts

Mailbox completion is normally sufficient review evidence. Require a durable
artifact only when the selected repository contract names the artifact path,
owner, and validator. The coordinator, not a reviewer, owns any required
durable capture unless the selected contract explicitly delegates it.
Before a large swarm, run a one-agent artifact probe only when runtime health
is uncertain or the selected artifact contract requires it; verify the probe's
assigned output.

Role names and routing metadata do not assign artifact-writing work. The parent
must explicitly assign that deliverable and its scope. Implementation children
may edit assigned source files and tests; reviewers normally remain read-only.
Preserve attribution in consolidated records: a child-reported result is not
independently reproduced evidence unless the coordinator actually reruns it.
The retired role catalog and routing map are removed. Dispatch through the active
tool using task scope and capability, not a named-role registry. Retained templates
and schemas support explicitly assigned artifacts and historical evidence only.
The stop hook records lifecycle completion, not acceptance. It does not parse
completion markers or validate files. For a required report, the coordinator
runs `python3 scripts/validate-agent-artifacts.py <artifact-path>` from
`codex/`, then checks candidate binding and provenance before accepting it.

### Artifact-required compatibility controls

These controls apply only when a selected artifact contract requires them;
they are not a prerequisite for ordinary Direct Work or a normal reviewer
return.

- **Path verification before delegation:** verify every required input and
  output path before dispatch so a `missing-file` failure is reported before
  work starts. When the selected contract supplies `agent-knowledge.json`,
  read it as advisory session context and include **Known current subagent risks**
  in the dispatch.
- **Structured blocker result:** use
  `STATUS: complete | blocked_runtime | blocked_missing_artifact | blocked_validation`
  and include `blocker_class`, `exact_failure`, the fallback attempted, and
  the coordinator's next action.
- **Artifact receipt:** a role that owns a required artifact returns
  `WROTE: <artifact_path>` only after the coordinator or deterministic
  validator can verify it. In an artifact-required route, missing artifacts are retried once;
  a second miss is a stated coverage gap rather than a
  manufactured success.

### Explicit subagent output controls

For an artifact-required route, the selected repository contract must identify
the minimum controls that make the output auditable:

- **Per-run provenance manifest** and an **Artifact validator** bind the
  artifact to its candidate and owner.
- A **Structured output schema** defines the verdict, findings, evidence, and
  claims boundary.
- **Eval fixtures**, **Positive-performance tracking**, and
  **Review-quality rules** prevent the contract from measuring only failures.

## Coordinator closeout

Wait for every requested subagent before synthesizing results. Verify that each
return binds the requested candidate and role, retry one malformed return with
a narrow follow-up, and state any coverage gap instead of inventing a verdict.
Do not claim a parent outcome complete from a subtask alone.
Close consumed agents when they are no longer needed.

For an artifact-required route, record **agents requested**, agents completed,
agents blocked, invalid returns, coverage gaps, and **agents closed**. Classify
every reported gate failure as **introduced by current patch**,
**pre-existing**, **unrelated dirty worktree**, or environment/tooling failure.
