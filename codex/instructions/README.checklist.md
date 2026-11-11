# Selected-Work Checklist

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Use this checklist when substantial work needs a quick scope and verification
review. It is not an additional admission gate for routine implementation.

## Before work

- Identify the requested outcome, owned paths, and applicable AGENTS guidance.
- Read only the skill and reference documents relevant to that scope.
- Resolve routine reversible choices from the request. Ask when a missing
  decision materially changes the outcome, risk, or authority.
- Use a short plan when dependencies need coordination; do not require an
  interview, fixed deliverable count, or repeated approval for specified work.

## Relevant contracts

- [Tooling](./tooling.md): discover the repository's tools and commands.
- [Validation](./agents/04-validation.md): choose focused checks and required
  broader gates; reuse a passing aggregate's recorded component coverage.
- [CODESTYLE](./CODESTYLE.md): route to the touched language or format.
- [1Password](./1Password.md): use the native `op-ssh-sign` contract for an
  authorized commit. SSH-agent authentication is not a commit-signing prerequisite.
- [Work rules](./work-rules.md): evaluate the loaded policy layers together;
  do not select a weaker rule file to avoid a prompt or prohibition.
- [Subagent governance](./agents/07b-agent-governance.md): use only when the
  AGENTS delegation admission rule is met.

## Before handoff

Report the result, actual checks and outcomes, and material limitations.
Keep local proof separate from hosted or runtime acceptance. A failed check
blocks its dependent claim, not independent authorized work. Preserve unrelated
changes and name any remaining action needed to finish the requested outcome.
