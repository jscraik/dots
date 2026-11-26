---
id: dots-provider-pr-descriptions
name: Dots provider PR descriptions
---

For a confirmed Dependabot or Codex Security PR, review its generated description
and any maintainer-added evidence together. Report missing evidence as one
actionable finding. Accept provider-native wording and headings.

- Dependabot must identify the dependencies, affected manifests or lockfiles
  and version changes. Look for relevant advisory or compatibility context.
  Confirm the author from GitHub's Dependabot bot metadata.
- Codex Security must identify the provider finding, explain the affected
  boundary and proposed fix, and identify which validation was executed.
  Confirm the finding's association through the provider or maintainer. A
  branch name, PR title, label or body heading alone cannot establish it.
- Both need concrete validation commands with outcomes or links to named CI
  checks with outcomes on the current PR head. Record validation that is
  missing or blocked. Generated static verification, planned tests and
  release notes do not establish executed validation.

Use the ordinary description criteria if the provider cannot be confirmed.
Apply the same source review, current-head checks and review requirements to
every PR. Follow the Dots [provider description guidance](../../codex/instructions/agents/16-git-and-release.md#provider-generated-pr-descriptions).
