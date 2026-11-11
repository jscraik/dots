# Instruction Front Door

## Start here

1. Read the active repository's `AGENTS.md` and this canonical `codex/AGENTS.md`.
   These references are checkout-relative even through a fixture projection.
2. Read [migration scope](migration-scope.md) for source ownership, missing
   dependencies, command boundaries and local-only data.
3. For technical implementation or review, read [CODESTYLE.md](./CODESTYLE.md)
   before task-selected modules. Use the active repository's actual toolchain.
4. For approval, review, release or audit work, read
   [agents/README.md](agents/README.md) and
   [agents/01-instruction-map.md](agents/01-instruction-map.md).
5. Read [tooling.md](tooling.md) and [1Password.md](1Password.md) when those
   routes matter. Discover skills in the current environment; missing Configs
   skills remain an explicit dependency, not permission to improvise a bypass.

## References by task

- [Portable command rules](work-rules.md) and
  [managed configuration](managed-configuration.md).
- [Validation contracts](validator-contracts.md) and
  [development workflow](codestyle/19-development-workflow.md).
- [Local user context](USER_PROFILE.md), [retired Local Memory](local-memory.md)
  and [conditional Project Brain reference](project-brain.md).
- [Codestyle module index](codestyle/README.md) and
  [instruction provenance](../templates/guidance-provenance.json).

Keep implementation single-writer. Use bounded independent review when risk
requires it; persistent multi-agent work requires explicit admission. Reuse
unchanged instruction reads. Read only task-relevant modules.
