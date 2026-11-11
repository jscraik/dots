# OpenAI Agent Workflow Playbook

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Default workflow](#default-workflow)
- [Delegation](#delegation)
- [Evidence and escalation](#evidence-and-escalation)

## Default workflow

1. Establish the named outcome, bounded scope, and current repository facts.
2. Read governing instructions and any triggered repo-local skill.
3. Make the smallest reversible change that satisfies the outcome.
4. Run the narrowest relevant proof, then widen validation in proportion to
   risk and repository policy.
5. Report the outcome, exact evidence, and any remaining boundary.

This is Direct Work. It does not require a named operating mode, a durable plan
artifact, or a multi-agent ceremony.

## Delegation

Follow the delegation admission rule in [AGENTS.md](../AGENTS.md).
Give each admitted lane a bounded outcome and return contract,
then wait for and verify the result before synthesizing it. See
[agents/07b-agent-governance.md](./agents/07b-agent-governance.md).
Bounded independent delegation and risk-selected review are Direct Work QA,
not Workforce admission. Persistent or background coordination requires Jamie
to select Workforce explicitly.

For admitted work, inherit the coordinator's model and context by default.
Override model, reasoning effort or fork depth only when the user, selected
contract or bounded task justifies the override and the active tool supports those
parameters. When using a fresh context, supply every required input in the
dispatch. Keep self-contained child tasks within their assigned scope; do not
give them peer coordination, cross-agent messaging or orchestration ownership.

## Evidence and escalation

Use live executable contracts and current runtime output over copied guidance.
Local checks, hosted CI, review state, tracker state, and mergeability are
separate evidence lanes. Ask for direction only when a decision is materially
ambiguous, risky, or outside the authorized scope.
