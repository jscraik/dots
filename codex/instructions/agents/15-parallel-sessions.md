# Parallel Codex Sessions

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Use conditions](#use-conditions)
- [Isolation](#isolation)
- [Integration](#integration)

## Use conditions

Follow the delegation admission rule in [AGENTS.md](../../AGENTS.md). Useful
parallel work alone is not admission. Otherwise keep one owner and one active
implementation path.

## Isolation

- Give concurrent implementation lanes isolated writes, using separate
  worktrees when checkout or generated-state collisions are possible. Read-only
  reviewers can inspect the same candidate without creating another worktree.
- Inspect worktree status before edits and preserve any dirty or owner-unknown
  checkout.
- Do not share generated state, runtime configuration, or branch-rewrite work
  between sessions.

## Integration

Reconcile against current main with a normal non-force integration. Resolve
conflicts in the owning branch, validate the merged candidate using its
repository command contract, and keep hosted readiness evidence separate from
local validation.
