# Dots repository guidance

This is a public-appropriate, inactive migration candidate. Configs remains the
live control plane until a separately authorised and verified cutover.

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
- Update the local, ignored `codex/FORJAMIE.md` handoff for guidance changes.
  Do not commit it. Preserve task-local ownership and validation evidence.
- Use one implementation writer. Sensitive policy changes need a bounded
  independent review. Reviews and local tests do not grant publication or
  activation authority.
