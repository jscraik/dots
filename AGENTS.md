# Dots repository guidance

Dots owns its current workflow and standards. Configs provenance explains
origins; it does not require obsolete processes or source-only commands.
Use the dots CODESTYLE front door and executable validation contract.

This repository owns reusable, public-appropriate configuration. Installation
and activation require separate authority and verification on the target
machine. Use its local installation receipt for current state; this file does
not authorise a cutover.

- Preserve other work. Keep changes inside the named candidate; use disposable
  homes under the system temporary directory for projection and hook tests.
- Keep credentials in 1Password. Sessions, auth state, local profiles, machine
  inventory, databases, caches and generated reports stay outside Git.
- Do not push, start hosted CI, install into the live home, change system policy,
  merge or deploy without the corresponding explicit authority.
- Read [the Codex baseline](codex/AGENTS.md) and its
  [migration scope](codex/instructions/migration-scope.md) for Codex work. Read
  [CODESTYLE](codex/instructions/CODESTYLE.md) before technical implementation.
- Use the [dots validation contract](README.md#verify-locally). The Configs
  aggregate commands retained in the library remain Configs requirements;
  dots tests do not replace them. Missing dependencies block only that lane.
- PR writing uses the shared structure in
  [codex/instructions/PULL_REQUEST_TEMPLATE.md](codex/instructions/PULL_REQUEST_TEMPLATE.md)
  as guidance. Dots has no tracked GitHub PR template; do not claim this central
  file is enforced by GitHub or by a repository-local body helper. Use only
  commands and receipt routes actually available for the target repository.
  When drafting, reviewing, or repairing a Dependabot or Codex Security PR,
  follow the [provider PR workflow](codex/instructions/agents/16-git-and-release.md#provider-generated-pr-descriptions).
- Update the local, ignored `codex/FORJAMIE.md` handoff for guidance changes.
  Do not commit it. Preserve task-local ownership and validation evidence.
- Use one implementation writer. Sensitive policy changes need a bounded
  independent review. Reviews and local tests do not grant publication or
  activation authority.
