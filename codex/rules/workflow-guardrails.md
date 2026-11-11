# Workflow Guardrails

## Table of Contents

- [Purpose](#purpose)
- [Priority Gate](#priority-gate)
- [Implementation Language](#implementation-language)
- [Truth Lanes](#truth-lanes)
- [Current Bootstrap Queue](#current-bootstrap-queue)

## Purpose

Use this rule surface to keep repeated workflow failures out of ordinary daily work. Durable fixes belong in deterministic scripts, schemas, hooks, tests, project rules, and validation wrappers. Skills route and interpret the work; they do not replace mechanical checks.

## Priority Gate

Run `python3 scripts/workflow-priority-gate.py --dry-run` from the `codex/` subtree when the daily workflow queue may contain open P0 guardrails relevant to the named outcome.

If the gate reports `blocked_by_p0`, assess whether the reported guardrail blocks the named outcome. Pause only dependent actions and continue independent authorized work. Do not adopt unrelated repairs without authority; retain the reported P0 action for work that depends on it.

Session start uses the same gate in warning mode so new Codex sessions surface open P0 workflow work before the user has to remember it.

## Implementation Language

- Use the repository's configured tracker for issues and priorities; do not
  assume a connector or skill is available in every session.
- Select the smallest repo-native proof and report exact `pass`, `fail`, or
  `blocked` outcomes.
- Convert recurring, evidenced friction into a narrowly scoped repository
  affordance only when existing controls are insufficient.

## Truth Lanes

Keep these lanes separate in closeout and verification:

- local code and validation
- generated artifacts
- runtime reachability
- remote branch and PR state
- hosted CI
- review-thread state
- tracker state
- merge readiness

Do not claim one lane proves another unless a repo contract explicitly joins them.

## Current Bootstrap Queue

The initial P0 queue in Linear project `Workflow Burden Reduction Guardrails`
is implemented locally. New blocking work should come from the latest daily
sweep report, a live Linear P0, or a freshly generated closeout receipt that
identifies an unclosed durable-control gap.
