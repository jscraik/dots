# dots

Reusable workstation configuration prepared from the private Configs repository.
Configs remains the active source until a separately verified cutover. This
repository does not install itself into the live home.

## Contents

- `Brewfile`: existing Homebrew package declarations; copying does not install packages.
- `mise/config.toml` and `mise/mise.lock`: workstation tooling. Moving `latest`
  versions have been resolved offline from the existing lock, including inline tables.
  The diagram CLI lock was reconciled to the source's explicit 1.1.0 pin after
  a names/version-only npm registry lookup confirmed that release exists.
- `terminal/`: Ghostty, Zellij and the minimal shared shell environment.
- `codex/policy.md`: portable working-policy candidate, not the full live control plane.
- `scripts/resolve-homebrew-bin.sh`: reviewed existing standalone resolver.
- `scripts/stage-home.py`: disposable-home staging, with no live-install mode.
- `migration-sources.json`: source and candidate digests, with transformations recorded.
- `requirements/python-document-reading.txt`: pinned optional document-reading libraries.
- `MIGRATION.md`: public, private and local boundaries, including Codex state.

## Verify locally

Use Python 3.11 or newer, without installing dependencies:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check-source.py
bash -n scripts/resolve-homebrew-bin.sh
gitleaks dir --no-banner --redact --log-level error .
```

For the real staging entrypoint, create an empty directory under the system's
resolved temporary directory and supply it explicitly:

```sh
python3 scripts/stage-home.py --target-home /private/tmp/dots-review-home
```

The target must already exist. The command refuses symlinks, source directories,
the live home and conflicting files. Repeating it with identical files is safe.
Existing machine-specific files are preserved; conflicting managed paths require
manual review. No package installation, tool trust, shell activation, background
updater, credential access or live projection occurs.

## Secrets and retained data

1Password owns credentials and signing secrets. Authentication state and Codex
sessions stay on each machine.
Do not add tokens, `.env` values, sessions, caches, logs, generated reports or plugin
caches. Private machine inventory and operational evidence remain in Configs for
now. Ignore rules protect future additions; they do not prove absence of secrets.

## Deferred integration

The full Codex config, hooks, rules, automations and validators remain coupled to
Configs. They have not been replaced by the short policy candidate; do not
install it over the current Codex instructions without a verified cutover.
Shell login and interactive profiles still depend on a workstation certificate
integration; they remain in Configs. No existing required CI check has been
retired. Native Ghostty/Zellij parsing and Linux-hosted staging remain separate
verification lanes.
Configs-specific root `.mise.toml` and its lock remain in Configs; they select
that repository's CI tooling rather than workstation defaults.

The CircleCI configuration checks this repository only; it does not replace
Configs' existing checks. Rollback for this local candidate is simply to keep
using Configs. No live configuration has changed and no history was copied.

