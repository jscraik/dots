# Public policy migration scope

## Authority and ownership

This library is a public-appropriate port of accepted Configs revision
`cfd2e591c1e9439363955ffa93b6f396afc7a4ad`, plus the explicitly reviewed,
content-bound hook-copy integration in `templates/hook-copy-provenance.json`.
The dots migration maintainer owns this port. Existing Configs work is preserved
separately and is not adopted, rewritten or replaced. The local installation
receipt records each machine's active source and rollback state; do not infer
that state from a repository document. Publication, live cutover and
managed-system installation require separate authority and proof.

`templates/reconciliation-provenance.json` records selected reusable pending
fixes in addition to that baseline. Their local integration does not accept or
merge their source PRs. Original check and review requirements remain intact.
Unknown security flags still require correlated authenticated native reports;
the pending extension that would admit them without those reports is deferred.
Experimental execution admission and host/container qualification stay outside
this port. Private task links and comment attribution are replaced in synthetic
test resources rather than copied as operational history.

The handover also carries the bounded handler-failure diagnostics from local
Configs commit `283db198d281e239524da23563bd3390fa9910c9`. Dots qualifies that
read-only source import in isolation; it does not claim source-PR acceptance or
adopt the separate execution-admission prototypes. Handler failures retain
their denial while reporting exit status and output presence without raw data.

The [Context ledger and provenance](../templates/guidance-provenance.json)
classify each source file and list deferred Context Pointers. The front doors
route portable instructions; modules retain the accepted safeguards and source
recipes. In those retained recipes, “this repo”, “parent repo” and
repository-specific package, skill, ADR, harness or aggregate commands refer to
Configs, not to dots or an unrelated project. Use the active project's declared
toolchain and checks. Do not copy a Configs package command into dots or invent
a missing no-op validator.

`${CONFIGS_CHECKOUT}`, `${CODEX_POLICY_SOURCE}` and `${CODEX_HOME}` in retained
examples are local path placeholders, not configuration values to discover from
sessions. Resolve them explicitly for an authorised task. Imported tools default
to disposable fixture admission. The isolated installation candidate additionally
recognises its fixed private package context; it checks source identity, the
target OS account or disposable home, and the named policy resources. This
context grants no task, review, credential, execution or activation authority.
Never direct an installation recipe at the real home as a way of validating it.

The [installation procedure](../../README.md#first-machine-installation-candidate)
reuses the existing projector and validators. Managed-only backups and readback
support cutover, repeat, interrupted-apply recovery and rollback in isolation.
All local stores stay on the machine; browser, pets and usage-data aliases are
preserved rather than moved. A rehearsal does not qualify external services,
native active-turn enforcement or live activation. The separate first-machine
acceptance and approval boundary remains in force.

## Checks and dependencies

The [dots README](../../README.md#verify-locally) owns this candidate's local
validation commands. Its full tests join policy generation, schema/profile
governance, hook discovery, consent, projection and native command-rule matching
inside disposable homes. All CLI-backed cases must run when claiming that lane.
A missing CLI is a failed or unavailable lane, never a successful skipped check.

Configs' `pnpm lint`, `pnpm typecheck`, `pnpm test`, deeper tests, codestyle
wrapper and original aggregates remain required in Configs. They are not
replaced by dots' fixture suite. The reusable `verify-work.sh --fast`,
instruction-routing, hook-governance and workflow/review helper graph is also
ported into dots; its accepted regressions run only in disposable resources.
`templates/helper-provenance.json` records that closure and the source-only or
external boundaries. Private inventory, operational metrics, credentials,
installed services and hosted evidence remain operator inputs, not public data.
Code that is present may still require an admitted fixture; file presence does
not make a live command available. Report the exact missing lane as blocked.
No full Configs aggregate or live acceptance is claimed by this port.

The isolated Desktop-compatibility candidate preserves only an explicitly
reviewed, private, installation-bound restart delta. Canonical policy remains
strict; a proposal's existence is not acceptance. See the
[candidate boundary](../../README.md#desktop-restart-compatibility-candidate).
It does not upgrade existing sealed packages or approve a live recovery action.

Review identity, exact-head freshness, completed coverage, zero outstanding
findings, current CI and unresolved-thread checks remain unchanged. The accepted
Git/release procedures still govern when that workflow is authorised. Copying
those procedures does not authorise review requests or remote mutations.

## Local and private information

- Credentials and signing secrets remain in 1Password. `.env` values, auth
  material, local inputs and private MCP endpoint bindings never belong in Git.
- Sessions, conversation history, SQLite state, caches, logs, plugin caches,
  generated reports, consent hashes and local backups stay on each machine.
- Personal profile bodies and machine inventory are excluded. The public
  `USER_PROFILE` documents are pointers to optional, operator-supplied local
  context outside Git. Missing personal context is not a validation failure.
- Dots uses Codex memory and task-local worklogs. Project Brain documentation is
  conditional reference material for repositories that explicitly adopt it;
  it does not create a new memory requirement. Preserve existing adopted
  repository records without copying them into dots.
- `codex/FORJAMIE.md` is an ignored local handoff. Guidance changes update it;
  it remains uncommitted and is not part of the projection map.

## Rules and managed requirements

The six `templates/rules/*.rules` own the current command decisions,
justifications and positive/negative examples. Their provenance records the
accepted migration baseline without requiring an obsolete allow. Raw `git
status` remains unmatched because repository-local `core.fsmonitor` can execute
a helper; automatic internal probes disable that program-valued configuration
at their call site. Only the exact paths for the two fixed-output authentication
canaries are rendered per fixture. No arbitrary auth command is allowed. The
strictest matching rule applies; an unmatched command still falls back to
sandbox, hooks, approval policy and task authority.

`templates/requirements.toml` preserves allowed approval and sandbox modes and
two exact MCP identities. Its private identity URL is rendered from that
fixture's canonical local policy, with no wildcard or extra identity. Rendering
does not install it. Administrative requirements belong in a separately
authorised managed payload or system location; placing a file in a user's
Codex home does not establish administrative enforcement. The fixture projector
does not target `/etc` or project a requirements file into the runtime home.

Native `execpolicy check` proves rule matching only. It does not prove active
session enforcement, approval grants, secret access or managed-system adoption.
Roll back this candidate by discarding its owned disposable fixtures. Do not
alter the live setup, other work or original Configs checks.

## Helper boundary decisions

MIG-HELPER-1 retains admission-before-import ordering in migrated entrypoints.
The dots maintainer owns this permanent compatibility decision: the specific
late imports carry `E402` annotations because moving them ahead of scope checks
would change the execution boundary. The annotations apply only to those imports,
not to a file or global lint exclusion. Parsed-code equivalence, admission
regressions and the full lint gate validate these mechanical cleanups.

MIG-HELPER-1 records the permanent compatibility decision for the migrated
helper graph. The dots maintainer owns it. Retain the accepted FactRegistry
callback boundary that turns any callback exception into a blocking violation,
and the conformance CLI's final exception-to-nonzero reporting boundary. Their
two `BLE001` annotations preserve existing failure semantics rather than hiding
errors. Narrow parser exceptions use their actual parser error types. The
accepted helper regressions and full local suite validate these boundaries.

MIG-HELPER-1 retains a terminal exception boundary in the configuration-scrub
CLI: unexpected parser failures return a nonzero, structured blocked result
before any write, without printing parser payloads. Only expected parse errors
may use its existing fallback. The inline `BLE001` annotation documents this
fail-closed boundary; it does not permit recovery or success after an unknown
failure. The dots maintainer owns the permanent decision and its real CLI
regressions in `tests/test_handover_validation.py`.

MIG-HELPER-1 also retains the single annotated `S102` execution in the inert
Configs cache-consumer fixture. It compiles bytes already read through the
validated file descriptor. Reopening the mutable cache filename would lose that
binding. The exception is limited to that existing snapshot-execution line;
it grants no provider execution or cache-bootstrap authority to dots, and does
not exempt other source from security linting. The dots maintainer owns this
permanent compatibility decision and its existing consumer regressions.

Only an explicitly declared disposable fixture root admits nested test homes;
all code, resources and overrides still stay below that root, which cannot be
the system temporary root or the real account home. The default single-home
admission remains unchanged. This supports original tests that switch temporary
homes without admitting any live path.

Hosted helpers, hook admission and direct readiness share provider-token and
auth-store admission. The effective GitHub store, its leaves and in-root aliases
are checked without reading credential contents. Mutable output directories
retain strict alias rejection; read-only fixture inputs retain canonicalisation
coverage and are traversed without admitting escaping descendants.
Git-reported metadata paths are admitted before write probes; a
linked worktree cannot redirect a probe to a sibling root. Auth wrappers retain
their existing trusted-binary checks and additionally confine the selected
1Password executable to the disposable root. These fixture controls do not
qualify live services or arbitrary unreviewed code.

The exact installed Python dependency versions may satisfy the existing wrapper
contract after an isolated import/version probe. Otherwise the original pinned
bootstrap route remains required; unavailable packages are not successful skips.

The helper aggregate checks its migrated file inventory before starting. A
missing helper fails rather than disappearing into the original optional-check
selection. Original Configs Git-hook and CI recipes live only in
`tests/fixtures/configs-contract/` for consumer regressions; they are never
installed as dots' hooks or selected as dots' CI. The generic public API rules
retain their default selectors with one fictional project mapping. Real
repository mappings, inventory and metrics remain private inputs.

The original core-hook harness consumes the publisher's validated core view;
it does not maintain a second Braid filter. Full-manifest discovery and consent
tests still cover the complete approved hook set. Its dedicated FIFO canary
unsets the outer fixture's `CODEX_HOME`, uses only synthetic injection and keeps
the original mount, alternate-path and no-secret-output assertions.
