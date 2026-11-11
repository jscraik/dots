# Public configuration and local Codex state

This repository is a candidate for public, reusable workstation defaults.
The existing private Configs repository remains authoritative until its
dependent configuration and checks have been reviewed and migrated.

## What belongs here

Version public-appropriate package declarations, pinned tool versions,
terminal defaults, reusable Codex guidance, and setup or validation scripts
after reviewing their contents and dependencies. The ignore file uses an
allowlist: a new path must be reviewed and explicitly added before Git sees it.
The scan in CI is an additional check; it cannot establish that all content is
appropriate for publication.

Keep machine inventory and operational records that need versioning in private
storage. Use 1Password for credentials. Authentication state, session history,
session indexes, memories, databases, caches, logs, temporary files and
generated reports stay on each machine. They are not copied to this repository.

## Codex runtime boundary

Codex owns its runtime state under `~/.codex`. The current installation still
uses Configs for its managed configuration, instructions, hooks, rules and
associated scripts. The full reusable policy and helper groups are now present
in the isolated candidate, with disposable projection and validation routes.
The short `codex/policy.md` remains an example, not the full control plane.
Local proof does not authorise changing the active source. Desktop-owned
preferences, consent, local sessions and credentials must be preserved during
any separately approved cutover.

| Surface | Destination and treatment |
| --- | --- |
| Reusable policy and non-sensitive templates | Review for the public repository; install only after checking parity with the current policy. |
| Managed `config.toml`, hooks, rules and validators | Portable templates and code are staged here; machine bindings and consent remain local. Configs still owns the live installation. |
| Codex sessions, archived sessions and indexes | Keep on the machine where they were created; do not sync them through this repository. |
| Authentication, secret values and sign-in state | Keep credentials in 1Password and runtime sign-in state local. |
| Memories, runtime databases, logs and caches | Keep local; they are not workstation configuration to publish or project. |
| Plugins, skills and automations | Retain their current provider- or application-managed installation and runtime state; do not copy caches into Git. |

The staging script supports disposable temporary homes only. It does not install
packages, activate runtimes, move credentials, sync sessions, or update the live
Codex home. Review the staged result before designing a live installation path.

## CI boundary

The CircleCI configuration validates only the contents of this repository:
source integrity, staging behaviour, shell syntax and secret scanning. It does
not replace Configs' existing governance, security, review or CI checks. No
cutover is complete until the checks relevant to the retained functionality have
equivalent evidence and the public project is connected to the intended Free
organisation.

## Plan to remove the Configs dependency

Status: isolated implementation; live cutover and retirement remain planned
and unauthorised. This candidate does not change the running Codex setup or
its checks. Keep Configs available until
all phases below have evidence. Maintain one authoritative policy source at
each phase; do not allow two independently edited live copies.

1. **Inventory the dependency closure.** Map managed configuration, instructions,
   hooks, rules, schemas, validators and their imports, commands, manifests,
   fixtures and dependencies. Start with Configs' `scripts/link-configs.sh`
   and `codex/scripts/install-codex-hooks.sh`. Classify every input as public
   reusable source, private machine configuration, secret or local runtime
   state. Record unresolved dependencies privately without copying their
   values into this repository. Exit: every projected file has an owner,
   destination and required check.
2. **Separate portable policy from machine configuration.** Prepare a public
   template and a private local configuration input for machine paths and
   account-specific settings. Preserve credential references through 1Password;
   never embed credentials. Validate the generated configuration before it
   replaces any runtime copy. Preserve Desktop-owned preferences and consent
   fields under the existing supported contract. Exit: equivalent effective
   policy in a disposable home, with no secret or machine inventory published.
3. **Move complete, reviewable dependency groups.** Copy public instructions,
   hooks, rules and validators with their necessary schemas, tests and pinned
   tooling. Do not copy Configs Git history. Adapt source-root resolution and
   packaging without dropping enforcement or replacing full policy with the
   short policy example. Keep each change within the applicable review budget.
   Exit: each group works with Configs unavailable in an isolated fixture.
4. **Port projection and prove preservation.** Adapt the existing projection
   mechanism rather than adding a competing installer. Use explicit disposable
   targets, retain copy-versus-symlink semantics, and reject conflicting or
   unsafe paths. Test repeat installation, invalid input, failed validation,
   rollback and preservation of caller-owned files. Sessions, archived sessions,
   indexes, memories, auth, databases, caches and logs must remain untouched.
   Exit: snapshots demonstrate that only intended managed surfaces changed.
5. **Restore equivalent validation in dots.** Map every retained Configs check
   to a dots command and evidence, including config, hook wiring, projection,
   policy and review-gate regressions. Resolve command admission through its
   supported policy route before execution. Run local checks first; only run
   hosted checks after explicit authority and verified Free allowance headroom.
   Obtain independent security review of configuration and projection boundaries.
   Exit: required checks pass with Configs unavailable; missing coverage blocks
   cutover, not unrelated local implementation.
6. **Cut over one machine, then the others.** Request approval of the exact
   reviewed candidate before changing live paths. Take a private backup of
   managed configuration and link targets, not a public session export. Switch
   managed sources, run the existing drift and startup checks, and verify normal
   Codex operation. If any check fails, restore the previous managed files and
   links without replacing sessions or credentials. Exit: the first machine is
   accepted and rollback is demonstrated before repeating on another machine.
7. **Retire Configs only after dependency removal.** Check active entrypoints,
   links, startup jobs and validators for remaining Configs dependencies. Retain
   private operational records separately. Archive or disable old CI only under
   separate authority after equivalent checks are established. Exit: no active
   Codex component requires Configs; retained private data remains accessible.

Jamie owns live-cutover and retirement decisions. The migration task owns the
implementation and evidence. Record progress in the existing task worklog;
this plan does not authorise publication, CI runs, runtime changes or archiving.

## Outstanding-source reconciliation

The local migration reconciles individual fixes rather than importing old
branches wholesale. Earlier branches can contain behaviour superseded by the
accepted baseline. The file decisions and digests are recorded in
`codex/templates/reconciliation-provenance.json`.

| Source material | Treatment |
| --- | --- |
| Reviewed regular hook-manifest copy | Retain the public publisher, validators and synthetic proof; align the library docs with regular-file publication. |
| Supported hook denial and accurate execution diagnostics | Port with the original selected regressions; direct syntax grants no extra authority. |
| Native review formats and authenticated history/receipt binding | Port compatible fixes while retaining identity, exact head, findings, CI, thread and quorum requirements. |
| Unknown security flags without independent corroboration | Defer that conflicting extension; keep the stricter native receipt requirement and its regressions. |
| Source/base/edit-bound review-request safeguards | Port code and synthetic regressions; do not send a request during migration. |
| Configs package/CI recipes and another project's workflow | Keep with their owners; they do not define dots' validation or deployment. |
| Experimental execution, host, image and runtime qualification | Keep deferred with the source coordinator; do not introduce an execution route through this port. |
| Machine plugin paths, trust hashes and operational records | Keep local or privately versioned; never copy consent, sessions, credentials or reports into the public tree. |
