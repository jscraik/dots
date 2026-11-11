# Reusable working policy

This portable subset is a migration candidate, not a replacement for the live
Configs policy. Repository-specific instructions and required checks still apply.

- Prefer current source, executable contracts and observed output to assumptions.
- Preserve unrelated work. Isolate writes when ownership could conflict.
- Use supported repository commands and the narrowest meaningful proof first.
- Preserve security checks, hooks, review requirements and approval boundaries.
- Separate local test results from hosted CI, review and merge-readiness evidence.
- Obtain credentials through 1Password. Do not print or persist secret values.
- Keep auth state, sessions, caches, logs and generated reports outside Git.
- Missing credentials must block only the operation requiring them; do not
  replace them with placeholders or weaken authentication.
- Remote publication, deployment, billing changes and merges require matching
  task authority. Read access or a local test does not grant that authority.
- Report exact verification commands, outcomes and material limitations.

