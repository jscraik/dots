# Git Workflow Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Branch and sync discipline](#branch-and-sync-discipline)
- [Commit discipline](#commit-discipline)
- [Pull request discipline](#pull-request-discipline)
- [Stacked pull requests](#stacked-pull-requests)
- [Enforcement](#enforcement)

## Scope

- This module defines Git workflow standards for local branches, commits, and PR preparation.
- For the broader feature lifecycle before Git operations, see [19-development-workflow.md](./19-development-workflow.md).

## Branch and sync discipline

- Start from the repository target base branch and keep your branch current before requesting review.
- Use explicit comparison ranges when summarizing change scope:
  - `git diff <base-branch>...HEAD`
- Do not bypass hooks or governance checks with `--no-verify`.

## Commit discipline

- Commit messages MUST follow the repository commit contract in [04-docs-config-and-release.md](./04-docs-config-and-release.md).
- Keep commits atomic: one logical change per commit.
- Commit validation claims MUST be evidence-backed and match commands actually run.

## Pull request discipline

- PR summaries MUST cover the full branch delta, not only the latest commit.
- When the active repository has `.github/PULL_REQUEST_TEMPLATE.md`, follow it
  exactly. A missing template does not justify inventing required sections.
- Testing sections MUST include exact commands and outcomes.
- If checks are blocked, record concrete blocker reasons rather than placeholders.

## Stacked pull requests

- Use a stack when changes depend on one another and each layer has a coherent,
  reviewable purpose. Independent changes can target the trunk separately.
  Keep each layer small enough to review; do not invent a global file-count gate.
- Record the trunk, ordered PRs and immediate parent of each layer in the PR
  description or task worklog. For a manual chain, the bottom PR targets the
  trunk and each higher PR targets the branch directly below it. Verify the
  hosted base rather than assuming the repository default is the comparison base.
- Review and scope each layer with `git diff <immediate-parent>...HEAD`. Pass
  `--base <immediate-parent>` explicitly to readiness and applicable receipt
  consumers. The helper's default branch is not a substitute for a verified
  parent. Keep integration tests against the trunk where required; distinguish
  cumulative integration scope from the layer's review scope and diff budget.
- Assign one writer to operations that rewrite or publish dependent branches.
  A lower-layer edit can require restacking every dependent layer. Preserve
  other owners' work, obtain matching rewrite/publication authority, and refresh
  hosted base/head evidence, checks and receipts after restacking. A retained
  provider approval alone does not prove the local gate accepts the new head.
- Distinguish a manual PR chain from GitHub's registered native stacks. Native
  stacks evaluate branch rules and Actions triggers against the trunk and expose
  stack metadata to workflows. Verify registration and provider behavior before
  relying on those semantics; CircleCI needs its own verified event contract.
- Merge a manual chain from the bottom, then verify the next PR's retargeting and
  complete remaining diff. A native upper-layer merge may also merge all lower
  layers: authorization and current readiness must cover every affected PR.
  Observe terminal hosted merge state before reporting completion.
- Current readiness helpers support explicit non-default bases. Native stack
  metadata, unchanged-diff approval carryover and atomic multi-PR merge are not
  qualified by that support alone. Use the existing verified path until those
  behaviors have focused proof; do not install a stacking tool as a prerequisite
  for ordinary work.

Provider reference: [GitHub stacked pull requests](https://docs.github.com/en/pull-requests/reference/stacked-pull-requests).

## Enforcement

- Before PR handoff, run and record:
  - `git status --short --branch`
  - `git diff <base-branch>...HEAD`
  - the active repository's validation contract from its CODESTYLE/README
- Validation evidence MUST use:
  - `Command: <exact command> -> pass|fail|blocked (<reason>)`
