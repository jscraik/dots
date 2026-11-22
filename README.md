# dots

Reusable workstation configuration prepared from the private Configs repository.
Installation and activation require separate authority and verification on each
machine. The local installation receipt records its active and rollback state;
this repository does not install itself into the live home.

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

### Desktop restart compatibility candidate

An installed config may gain Desktop-owned executable registrations after a
restart. The ordinary check and rollback continue to reject those newer bytes.
The isolated compatibility candidate adds `prepare-desktop-review` to the
installer. It writes a private, create-once proposal in installation state and
returns its SHA-256; it does not approve the proposal or change runtime files.
Later proposals use digest-named files, preserving earlier proposals and pins.
The explicit digest selects the reviewed snapshot; a changed runtime still
invalidates an older snapshot. Oversized proposals are rejected before writing.
Only twelve named Desktop slots and newly granted native user-hook consent
for this installation may differ. All remaining parsed policy must
agree with the installed baseline, and every other managed target must match.

After independent review and explicit operator acceptance, `check` or `rollback`
can receive `--desktop-review-sha256` with that exact digest. Checks never learn
new settings automatically. Changed executable arguments, environment values,
plugin settings, unknown fields or safety policy still block. Canonical schema,
hook and rule validation remain intact. The review-aware drift checker is
read-only; it refuses `--repair` rather than deleting retained registrations.
Ordinary packaged repair, initial preparation and the historical notifier
scrubber also stop before writing when that Desktop registration is present.

Reviewed rollback derives its target from the original backup and the exact
Desktop delta. It preserves original plan, receipt and backup files, and keeps
a separate digest-bound recovery receipt for interrupted retries. Newer or
concurrent edits stop restoration without granting overwrite authority. The
review proposal contains private configuration and must remain outside Git.

The source supports newly built packages; a disposable rehearsal does not
prove acceptance on a particular machine or authorise live recovery. An existing
sealed package must not be edited or have its recorded hashes rewritten to make
this route available.

The pure `desktop_compatibility.repair_candidate(installed, observed)` API can
prepare configuration text for the bounded seven-field repair. It preserves
the named Desktop preferences and app-tools enabled flag, restores a missing
canonical `multi_agent` flag, and removes only the reviewed legacy sandbox
aliases. It does not write files, approve a proposal or clear the observed
drift. Ordinary check/review continues to reject the unrepaired configuration.
After separately authorised publication, a fresh content-bound Desktop review
is still required. Custom Chrome theme additions and code theme IDs other than
the verified `codex` ID remain blocked pending their schema port. Automatic
archive days remain local lifecycle settings and must be nonnegative integers.

The paired generator can restore sealed Braid command quoting and the original
matching consent hashes together. It accepts only equal literal arguments and
unchanged handler metadata; it creates no new trust hashes or trust exceptions.
Either mixed file pair remains blocked by the existing review checks. Micro
layout preservation supports only the verified bundled TOML bindings plus the
separate-microphone-keys boolean. Other bindings remain blocked. These are text
candidates; publication and exact-content acceptance retain separate authority.

### Local checks

Use Python 3.12 or newer in an existing validation environment containing the
pins in `requirements/codex-validation.txt`. The instruction-pointer checker
uses the already-declared `markdown-it-py==4.2.0`. No online bootstrap or new
dependency is added by this migration.

Without the separately administered `/opt/dots-hook-tools` installation, local
installation-route operator tests report an explicit skipped prerequisite.
Component tests still run; skipped operator tests do not prove installation or
protected-runtime acceptance. Disposable CI provisions and validates the real
toolchain first and sets `DOTS_REQUIRE_PROTECTED_TOOLCHAIN=1`, so a missing
prerequisite fails that lane instead of producing skipped operator coverage.
CI first runs the three regressions observed failing before the previous timeout,
then the complete suite. It stops at the first failure to preserve its traceback;
a passing run still executes the complete suite.

```sh
python3 -m unittest discover -s tests -v
ruff check --no-cache .
python3 scripts/check-source.py
python3 -B scripts/check-public-guidance.py
bash -n scripts/resolve-homebrew-bin.sh
gitleaks dir --no-banner --redact --log-level error .
```

For the real staging entrypoint, create an empty directory under the system's
resolved `/tmp` directory (`/private/tmp` on macOS) and supply it explicitly:

```sh
python3 scripts/stage-home.py --target-home /private/tmp/dots-review-home
```

The target must already exist. The command refuses symlinks, source directories,
the live home and conflicting files. Repeating it with identical files is safe.
Existing machine-specific files are preserved; conflicting managed paths require
manual review. No package installation, tool trust, shell activation, background
updater, credential access or live projection occurs.

The reusable Aikido launcher is included under `codex/scripts/`. Its executable
and 1Password reference file remain local. The launcher retains the existing
1Password route and pinned-binary requirement; tests use synthetic providers
inside disposable homes. No provider is installed or authenticated by the port.
Packaged provider admission recognises its named local binary/reference inputs
and the existing 1Password CLI locations. It adds no writable helper roots;
rehearsals continue to reject host providers and escaping symlinks.

Machine admission treats `CODEX_APP_TOOLS_PIPE_PATH`, `CODEX_TECTONIC_PATH`,
`CODEX_APP_RUNTIME_CLI_PATH` and `CODEX_MCP_NODE_PATH` as unused native app
metadata. Migrated handlers do not open or execute these
values, and they add no resource roots or helper-output permissions. Event paths,
all other scoped environment paths and retained-store protections remain
checked. Rehearsals still reject native metadata paths outside their owned home.

Machine event working directories also recognise explicit trusted projects in
the owned runtime configuration. This admission is limited to the registered
directory and its descendants, rejects aliases and unsafe directory modes, and
retains the installed managed-worktree checks. Runtime trust does not add
helper-output or environment-resource roots. Rehearsals retain sealed-policy
containment; session and credential stores remain protected.

## First-machine installation candidate

### Protected hook tools prerequisite

Prepare the complete Python, jq and GitHub CLI payload on its native platform
using the reviewed artifact lock. Supported targets are macOS ARM64 and Linux
amd64. The protected bootstrap requires `/usr/bin/python3` version 3.9 or newer
(Command Line Tools Python on macOS). Installation preparation checks this
route before publishing hooks. Preparation uses disposable storage and installs the hash-locked Python
validation dependencies inside that payload.

```sh
python3 -I codex/scripts/prepare-hook-toolchain.py --platform darwin-arm64 --output /tmp/dots-hook-tools
python3 -I codex/scripts/install-hook-toolchain.py --payload /tmp/dots-hook-tools --inspect
```

Review the payload and the printed inventory digest before the separate admin
step. Supply that exact digest as `REVIEWED_DIGEST`. Provisioning requires
system Python with isolated mode and publishes a root-owned version under
`/opt/dots-hook-tools`. `--select` explicitly selects that version for hooks.

```sh
sudo /usr/bin/python3 -I -S codex/scripts/install-hook-toolchain.py --payload /tmp/dots-hook-tools --reviewed-sha256 REVIEWED_DIGEST --select
```

Complete this prerequisite before preparing a new Codex installation. New
preparation captures the selected version and its complete inventory digest in
the sealed package and plan. Apply rechecks it before any runtime publication,
and check refuses a changed, missing or unbound selection. An administrator
changing the selection requires a fresh preparation. Historical unbound plans
remain readable for recovery through their exact previously prepared package
entrypoint, state directory and plan digest (see recovery below). The updated
checkout dispatcher does not authenticate legacy origin receipts and refuses
them; it must not execute historical payloads on an unverified caller manifest.
Legacy plans do not provide new apply/check readiness through this installer.

Installer children and packaged projection use the verified versioned Python
from this protected toolchain. They do not reuse a mutable caller venv launcher.
Machine wrappers ignore caller Python overrides and writable mise/venv fallback
roots. Disposable fixture resources have a separate system-Python admission
before their explicit test interpreter is used; that route grants no live-home
installation or activation authority.

Existing mise-only installations need this admin step before adopting these hook
launchers. Full installation and Linux CI verification of this candidate are
pending.

LifeOS retrieval needs an optional Bun executable in the protected toolchain
and a separately admitted private retriever. Before calculating the payload's
reviewed inventory digest, stage an independently verified, platform-compatible
Bun artifact at `bin/bun` beside Python/jq/gh. This repository does not supply a
Bun download pin: artifact identity and provenance need separate review. The
normal admin installation inventories and checks this optional provider, and
the installed package binds its exact toolchain version. Changing Bun requires
a newly reviewed payload and installation; no live-home activation is implied.
The adapter selects only that bound `bin/bun`. `CODEX_LIFEOS_BUN`, Homebrew,
mise and inherited PATH no longer select providers. Remove the legacy override
from the launch environment. The private retriever and data paths retain their
existing resource admission. Without optional Bun, retrieval returns no context;
it does not clear a security decision. The retained LifeOS harness covers synthetic provider routing and
the minimal child environment.
Readiness helpers use a separate repository-scoped contract for verified managed
worktrees. It admits contained scope and waiver inputs without adding general
resource roots. Receipts use regular JSON leaves in an existing owned `.tmp`
directory; the default is `.tmp/pr-readiness.v1.json`, not shared Git metadata.
Symlinks, hardlinks, nonregular or unsafe output leaves, retained stores and
installation resources remain rejected. Publication rechecks the worktree and
parent identities and uses a no-follow temporary file and atomic replacement.
These checks detect observed replacement races; they do not claim immunity to
hostile concurrent filesystem changes. Admission does not waive any readiness
head, review, CI, scope or receipt-freshness gate, or grant remote authority.

The body-only PR helper uses this same selected-repository boundary for managed
worktree inputs. It snapshots the admitted body and template, then rechecks the
worktree identity before a hosted operation. Its current-head receipt or explicit
metadata-repair preflight, PR number and repository checks remain required.

`scripts/install-codex.py` provides one local procedure: `prepare`, `apply`,
`check` and `rollback`. It reuses the existing projector, full policy validator,
Desktop-setting preservation and atomic config/hook publishers. It installs no
packages, starts no background service and does not contact a provider or CI.

The projector bootstrap uses the installer's selected Python through the existing
`CODEX_VALIDATION_PYTHON` contract, including quoted paths containing spaces.
<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:cb3654d2c3df54a2c07c62809a85870e0dbea6d5a0bee52afb9eb31f730e263b -->

Full-policy disposable fixtures also select `CODEX_VALIDATION_PYTHON` before
admission checks. Preview fixtures use `/usr/bin/python3`; the selected absolute
executable must provide Python 3.9 or later. Full-policy validation additionally
requires the validation environment described above. Projector children use a
fixed system PATH.

Standalone projection requires this sanitized launcher (append projection flags):

```sh
/bin/bash -p scripts/link-configs.sh --help
```

Privileged Bash startup ignores `BASH_ENV`, `ENV` and exported shell functions
before reading the script. The executable script uses the same protected
shebang. Plain `bash scripts/link-configs.sh` with an inherited environment is
unsupported. The in-script unset protects child processes. The packaged
installer supplies an allowlisted environment; installed audit and repair
wrappers use the protected launcher and pass their selected absolute Python.

<!-- /coderabbit-ai-generated:v1 -->

Preparation requires the exact full commit ID already checked out as `HEAD`,
refuses tracked or nonignored untracked changes, and creates the package from
that commit's immutable Git tree rather than worktree bytes. Its private
`origin.json` receipt records the commit, tree digest and complete blob inventory.
It then validates the read-only policy package before backing up the 20 managed
targets. Config, hook manifests, profiles and reusable code are independent
regular-file or directory copies. The additional private
`.dots-package.json` reference identifies the sealed installed package without
using a filesystem link. Copied helpers validate that package and the installed
code inventory before use. Development-checkout edits cannot change the running
installation. Existing
agents, automations, usage data, browser/pet state and all session/auth stores
remain local. Backups cover managed files and link metadata, not those stores.
The sealed package records the existing session-evidence storage root from its
private bindings. Governance still requires that exact root in the selected
permission profile; preparation does not create it, move sessions or add a
replacement permission. Rehearsal roots remain confined to their disposable home.
On macOS, machine scope also recognises the owned user temp directory returned
by the OS when the existing permission profile extends `:workspace`. An
arbitrary `TMPDIR` cannot select a new root. Retained-store and alias denials
still apply; rehearsal and read-only profiles gain no host temp access.
Bulk admission inspects every output leaf while resolving shared roots once
per event. It refuses changed root aliases before a handler can run.

Rehearse only in an owned disposable home under resolved `/tmp`, with an existing
synthetic Codex setup and private binding JSON. The test entrypoint builds that
setup and exercises the actual commands:

```sh
DOTS_CODEX_BIN=/absolute/path/to/codex python3 -B -m unittest discover -s tests -p test_installation_route.py -v
```

For native hook consent, `hooks/list` with `cwds` proves on-disk discovery only.
After an authorised change, use the owning app server's `config/batchWrite` with
`reloadUserConfig: true`, then verify `hooks/list` with the target `threadId`.
A successful `config/value/write` or fresh-server listing does not prove that an
already loaded thread uses the new hooks. The focused `test_hook_discovery.py`
regression checks this distinction in a disposable home without a model turn.

After granting native hook consent, preserve it through the existing
`prepare-desktop-review` proposal and explicitly accepted
`--desktop-review-sha256` check/rollback route. Inspect the proposal's exact
`hooks.state` identities and hashes against native discovery before accepting
its digest. Preparing or printing the proposal does not authorise consent.
Only new consent for this installation's `.codex/hooks.json` can use this route;
replacement of an existing trusted hash remains blocking. Ordinary projection
and startup repair stop before changing consent-bearing configuration. Generated
bindings still cannot install trusted hashes, and any later runtime change
invalidates the accepted snapshot.
This review also supports a first installation with no previous config. The
sealed plan must record that absence and no config backup may appear later.
An explicitly pinned preserving rollback retains a consent-only config in that
case, restores the other targets, and leaves the original installation receipts
and absent backup unchanged.

For an operator-prepared rehearsal, the command sequence is:

```sh
python3 -B scripts/install-codex.py prepare --mode rehearsal --home TEMP_HOME --state-dir TEMP_HOME/installation/one --bindings BINDINGS_JSON --braid-bin BRAID_BINARY --source-revision REVIEWED_COMMIT
python3 -B scripts/install-codex.py apply --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
python3 -B scripts/install-codex.py check --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
python3 -B scripts/install-codex.py rollback --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
```

Substitute explicit paths, the full reviewed commit currently checked out as
`HEAD`, and the digest returned by preparation. That digest identifies the
prepared change; it grants no execution or installation authority.
Do not edit the source or package between commands. Repeated application is a
check. Interrupted application can be rolled back without resuming activation.
Unexpected newer target content stops recovery and retains the backup for inspection.
Managed directory inventories include nested modes and file hashes. Displaced trees
are retained privately, not recursively deleted. On macOS, directory swaps briefly
need owner-write permission; an inode-bound journal is flushed before that change
and recovers the original modes after interruption. Recovery refuses replaced or
ambiguous inodes rather than changing an unrelated directory.

Updates use the same `prepare`, `apply`, `check` and `rollback` commands with a fresh
state directory and bindings rendered for that package. Preparation refuses managed
runtime drift; review intentional edits before updating rather than overwriting or
uploading them. Only selected reusable changes belong in the GitHub source. Private
bindings, Desktop consent, authentication, sessions, databases, plugins and generated
state stay local. No automatic bidirectional sync or background service is added.
Existing private data aliases are preserved; their relocation is a separate task.

For an already applied generation with an accepted exact Desktop review,
`prepare --previous-desktop-review-sha256 DIGEST` can preserve that reviewed
state through an update. The old reference, plan, review and every managed target
must still match. A sealed descriptor carries the approval identity into the new
package; canonical policy stays separate from the reviewed Desktop overlay.
Preparation and application revalidate it. Newer registrations, changed reviews,
new installation references and conflicts with new canonical policy remain
blocking. Ordinary preparation without the pin retains its existing rejection.
Rollback restores the exact pre-update configuration and prior package reference.
Repeated updates preserve the accepted effective values and absences of the
existing finite Desktop registration slots, even when a later review records
no new delta. The previous canonical snapshot is authenticated against its
package inventory before supplying conflict-check baselines. New canonical
conflicts and unreviewed runtime edits still block; themes and archive choices
retain their existing canonical transition rules.

An exact Desktop review can also retain the selected model, reasoning effort and the typed,
account-scoped `desktop.daybreak-enabled` preference. Account identifiers stay
in private runtime evidence, never in this repository. Review does not change
the provider, permissions, tools or service credentials. Existing hook identities
may change only their explicit `enabled` boolean: trust hashes and every other
field must remain unchanged, including in the rollback configuration. A missing
rollback identity is rejected rather than creating a new trusted hook. Native
hook discovery and loaded-session verification remain separate from config review.

When separately approved model, reasoning, project-trust or presentation choices
already differ from the installed policy, first express them in the public root
template and private project bindings. The source-only `prepare-policy-update`
operation prepares a new generation without clearing the old generation's drift.
It takes the ordinary `--home`, fresh `--state-dir`, `--bindings`, `--braid-bin`
and `--mode` arguments, plus `--source-revision` naming the full reviewed commit
currently checked out in the clean source checkout, and all six exact SHA-256 pins:
`--bindings-sha256`, `--previous-plan-digest`, `--previous-package-digest`,
`--previous-marker-sha256`, `--previous-expected-config-sha256` and
`--previous-observed-config-sha256`. Obtain them from the reviewed private inputs,
old sealed generation and current runtime immediately before preparation.

This route preserves the currently selected model, reasoning effort and typed
Daybreak preference from the pinned runtime,
the four explicit private project bindings `value_0174`, `value_0175`, `value_0176` and `value_0177`, and the
two existing validated presentation preferences and the source-selected
`desktop.autoArchiveAfterDays` value, plus the source-selected absence of obsolete
`marketplaces.openai-primary-runtime.last_updated` metadata. Other marketplace
fields and every other setting remain under strict comparison; the Desktop
review remains explicit and the previous sealed generation remains unchanged.
The existing equivalent legacy sandbox spelling may be normalised to the same
named permission profile; a different permission or network capability is rejected. Existing project trust must be
preserved; package-local project references move with the normal generation.
The exact observed config must match that transformation of the verified old
baseline. Any other policy delta, changed managed target, old receipt or package
blocks preparation or application. The accepted Desktop executable registration
overlay is carried separately; the two presentation preferences now follow the
new canonical template rather than the older overlay.

If another workspace was registered after the previous installation, select its
absolute path explicitly in the private bindings' optional
`additional_trusted_projects` list. The binding pin and sealed canonical output
cover that selection; it is never imported automatically from runtime state.
Entries must be unique, must not replace an existing template binding, and add
only `trust_level = "trusted"`. The exact runtime comparison still rejects
unselected project registrations and any change to existing trust. With no list,
all generated policy remains byte-for-byte unchanged.

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:ace8d96a672cc207d19a867e439c04f7cd4abd5c316da51599d1997225313da1 -->

The supported native-consent route starts from generated policy without
`hooks.state`, followed by a separately accepted installation-bound consent
proposal. Revocations from that pinned native-consent installation are
preserved through preparation, application and repair readback.

Older packages whose generated canonical policy already contains `hooks.state`
are not supported by this update route. The update refuses that baseline rather
than treating generated hashes as proof of operator consent or silently
discarding later consent. Adopting the new format requires separately reviewed
reprovisioning; this PR provides no automatic conversion of the older format.
An initial installation with unbound state likewise stops without changing it.

For a supported consent-free installation, prepare and apply it, grant fresh
native consent for the installed hooks, and run `prepare-desktop-review`.
That command requires an applied installation; it cannot repair an unsupported
older baseline or resolve unbound consent before installation.

<!-- /coderabbit-ai-generated:v1 -->
Existing `enabled = false` flags do not authorise changed trust
hashes or new identities. If every recorded hook was disabled, replacement
identities also remain disabled. A transition never grants hook consent.

A standalone live `repair-usage-directory` forward swap is refused before any
change: replacing a retained link would invalidate the active deployment's
ownership record. Rehearsal and explicit recovery remain available. A previously
applied repair can be included in `prepare-policy-update` through its exact
`--usage-directory-repair` proof; preparation verifies the retained directory,
original link backup and previous package. Rollback restores the original link
and retains new usage logs in repair storage. Do not cancel a prepared migration
as routine cleanup: its rollback includes that retained-resource inverse.

Preparation seals a private transition proof and leaves the runtime untouched.
Normal `apply`, `check` and `rollback` retain their gates and exact plan pin.
Rollback restores the selected pre-update bytes and prior package reference;
the old check will still report their intentional policy drift. It does not
retroactively accept those preferences under the old template. This operation
does not grant installation authority or import arbitrary runtime-only policy.

For recovery after the development checkout changes, use the exact previously
prepared package entrypoint, state directory and plan digest, for example
`python3 -B STATE_DIR/payload/scripts/install-codex.py rollback --state-dir STATE_DIR --plan-digest PREPARED_DIGEST`.
This pinned local recovery route needs the same authority as rollback and must be
available outside an affected assistant chat. The original checkout entrypoint still
refuses source mismatches. Disposable recovery proof is not live Studio acceptance.

The candidate also distinguishes the current OS account home from disposable
homes. That admission is not live qualification. A quiet maintenance window,
private binding and external-dependency checks, current consent, independent
review and a separate activation decision are required for each machine. The
local installation receipt records whether that machine is active or rolled
back; the repository does not change `/etc/codex` policy. Without a packaged
context, all imported tools retain their original strict fixture guard.

## Synthetic Codex projection preview

The first projection increment uses an explicitly synthetic public template
and a one-field machine-input contract. It is not the full managed Codex
configuration and must not be installed as active policy. It adds no dependencies.

Create an empty directory under resolved `/tmp`, then
run the entrypoint with that directory substituted for `TEMP_HOME`:

```sh
python3 -B scripts/preview-codex.py --machine-input tests/fixtures/codex-machine.json --target-home TEMP_HOME
```

`TEMP_HOME` must already exist. The input JSON accepts only `project_root`, an
absolute path, and rejects duplicate or additional fields. The example uses
an invented path; real private inputs stay outside Git. No secret values are
accepted or needed. The renderer quotes that path, parses the resulting TOML,
and checks the exact synthetic policy before staging any files.

The result is `.dots-preview/codex-config.toml` plus the existing disposable
defaults. It never replaces `.codex/config.toml`, hook files, sessions or auth.
Conflicting existing files and symlinks are rejected. The existing temporary-home
restriction still applies. This is a preview operation, not a transactional
live installer: filesystem errors can leave newly created disposable defaults.
Discard the owned disposable home to roll back; never use it as a real Codex home.

Run `python3 -B -m unittest discover -s tests -v` for both existing and new
regressions. The new tests exercise the actual CLI, preserved synthetic runtime
sentinels, idempotence, input rejection, quoting and conflicting targets.
The fixture is an explicit file, not a copy of private Configs or its untracked
files. The joined fixtures below cover full policy generation, schema/profile
validation and accepted hook-copy integration. No Configs checks are retired;
live cutover remains a separate, unauthorised operation.

### Accepted projection core fixture

`scripts/link-configs.sh` is imported from Configs commit
`cfd2e591c1e9439363955ffa93b6f396afc7a4ad` and restricted for this migration:
it requires an existing temporary HOME, explicit Codex scope and target,
rejects symlinked home content, and admits only the synthetic preview map.
Legacy profile and agent-manifest retirement is excluded from this preview
route; caller-owned state is preserved rather than migrated implicitly.
The copy/runtime-copy/symlink implementations remain present. This smaller map
exercises plain-copy projection; the full-policy fixture below separately
exercises the migrated runtime-copy validators and reviewed hook publisher.
The preview map cannot select those broader resources.

`tests/test_projection_core.py` constructs a disposable checkout from exactly
two allowlisted source files plus generated synthetic configuration. It does
not copy the private Configs tree, its history, or untracked files. The test
runs the imported projector's repair/check/repeat sequence, checks local-state
preservation, and rejects missing inputs, unsafe scope, symlinks and a changed
map. There is no active `codex/projection-map.json` in this checkout: the map
exists only inside each test fixture. These are single-process disposable
tests, not proof against hostile concurrent directory replacement or proof of
live-cutover readiness. Do not run the imported installer against a real home.

## Secrets and retained data

1Password owns credentials and signing secrets. Authentication state and Codex
sessions stay on each machine.
Do not add tokens, `.env` values, sessions, caches, logs, generated reports or plugin
caches. Private machine inventory and operational evidence remain in Configs for
now. Ignore rules protect future additions; they do not prove absence of secrets.

## Full policy generation candidate

`scripts/generate-codex-policy.py` now renders the complete accepted root
configuration and seven standalone profiles. The reviewed JSON template stores
the parsed policy, including approval, permissions, profile isolation, hook
enablement and delivery instructions. Whole-string local slots separate machine
paths, private endpoint and application identities, and personal Desktop state.
Persisted hook trust is deliberately excluded. Source revision and file digests
are in `codex/templates/policy-provenance.json`. JSON is the source format for
this candidate; generated output is TOML. Comments are not reproduced.

Run the synthetic, local-only generation check:

```sh
python3 -B scripts/generate-codex-policy.py --bindings tests/fixtures/policy-bindings.json
```

The command generates all eight policies in memory and verifies TOML round-trip
equality. It emits a count only, never binding values, and installs nothing.
Bindings must supply exactly the referenced string slots; duplicate keys,
missing/extra bindings, non-string values and table-key collisions are rejected.
Quoting prevents binding text from becoming TOML syntax. Bindings are trusted
local configuration inputs, not a permission-grant mechanism. They can change
machine-specific keys and values and therefore still require the complete
governance validation before installation. The generator rejects any
`hooks.state` table and treats historical hook-consent bindings as unknown input.
Never supply credentials as bindings.

The synthetic bindings are invented strings for serialization testing, not
working endpoints, valid hook consent or a deployable workstation configuration.
Private reconstruction was compared against the accepted source: all eight
parsed policies matched before the integration adaptation below. The template
also retains the newer draw.io registration with its source path in a local
slot. Hook definitions remain discoverable, but generated policy starts without
trusted hashes so the native runtime must obtain fresh consent for the exact
current hooks. The reviewed disabled-transport adaptation remains in place.
The accepted validator's schema feature/approval-mode
parity and seven-profile policy, transport and OSS-isolation checks passed on
that reconstruction. Negative probes rejected weakened approvals and isolation.
Those checks are bounded validation, not full JSON Schema validation or a run
of the complete governance validator. Their task-local evidence stays private.

The complete configuration governance validator, runtime repair library, schema
and compact prompt are now ported under `codex/`. Their checks retain the
accepted source logic with home-relative machine paths. The port is gated by an
explicit disposable `DOTS_TEST_HOME` matching `HOME`; resource overrides cannot
leave that home. The root must be under resolved `/tmp`, never an account-home
descendant. `TMPDIR`, `TEMP` and `TMP` cannot expand this boundary. It is an
inactive candidate, not a live installation command.
No Configs check is removed or replaced by the renderer tests. The preview route
retains its closed synthetic map. A separately selected full-policy fixture
route now exercises the complete generated bundle, as described below. Both
routes reject live homes. Keep using Configs until a live cutover is accepted.

`tests/test_governance_port.py` constructs the complete configuration-validation
fixture from an explicit dependency list. It generates all profiles, creates
invented registry manifests and separate runtime files, then runs the real
validator in snapshot and full runtime-layout modes. It also invokes the real
repair entrypoint after injecting approval drift, verifies restoration and
preserves synthetic auth/session/database sentinels. No hook handler is executed.
The fixtures do not copy installed plugins, sessions or private repository files.

The suite rejects missing schema, profiles and registry manifests, weakened
policy, incomplete hook manifests, hard-linked hooks and outside targets. A
missing schema retains the validator's unavailable result; it does not pass.
The renderer uses conventional TOML tables because the preserved repair parser
does not support every equivalent inline-table spelling.

Run the full candidate suite with `python3 -B -m unittest discover -s tests -v`.
This covers the migrated configuration validator, inactive publisher and real
handlers. Installed-runtime discovery is a separate explicit local command
described below. The suite does not run Configs' complete repository suite or
the live drift guard. Existing Configs gates remain authoritative for the live
setup. Synthetic marketplace fixtures prove validation behaviour, not
availability of installed plugins.

### Reconciled pending fixes

The inactive port also contains selected reusable pending fixes: supported hook
denial, precise execution-authority diagnostics, native review presentation and
history binding, and source/base/edit checks for review requests. The original
check, identity, freshness, coverage, thread and quorum requirements remain.
Completed unknown security flags still need correlated authenticated reports;
the conflicting extension that would admit them without those reports is deferred.

Run their original selected regressions and composition checks with:

```sh
python3 -B -m unittest discover -s tests -p test_pending_fixes.py -v
```

The maintained readiness loader includes its native, structured-summary,
review-request and maintainer-acceptance suites. They are not separately repeated
by the helper integration. Synthetic fixtures retain the provider layouts with
private task links and source-comment attribution replaced.

`codex/templates/reconciliation-provenance.json` binds the selected file set and
multi-source decisions. The dots maintainer owns it; `scripts/check-source.py`
consumes its digests. The earlier manifests retain accepted-source provenance,
so this records pending overlays without rewriting that history. It grants no
source acceptance, hosted clearance or installation authority. Experimental
execution/host/container qualification, machine consent and project-specific CI
changes remain outside this port.

### Reusable helpers and validation closure

The workflow, governance, review-lifecycle and Git-metadata helpers are ported
from the accepted revision. `codex/templates/helper-provenance.json` records
their origins, transformations and public-resource decisions. Git metadata
inspection uses the revision-bound sibling core in dots; it no longer needs a
separate Configs or Agent-Skills checkout. Each project still owns its own
toolchain, checks and repository hooks.

Run the focused integration through the maintained tests:

```sh
python3 -B -m unittest discover -s tests -p test_helper_dependencies.py -v
```

The fixture generates a complete temporary policy, fictional workspace
inventory and metrics, local Git history and synthetic runtime sentinels. It
runs the accepted helper regressions, the original core-hook harness and the
real `verify-work.sh --fast` entrypoint against those resources. No real
inventory, sessions, auth state or provider credentials are imported. Original
Configs consumer recipes are inert files under `tests/fixtures/configs-contract/`;
the tests do not install their Git hooks or execute their deployment/CI setup.

The aggregate rejects missing migrated helpers before optional selection can
skip them. Its inherited plan/skill/maintenance and cross-workspace fast-mode
exclusions remain visible; this is no substitute for Configs' package gates or
for a live, multi-project audit. The Python wrapper may reuse an explicitly
selected interpreter only after the exact existing dependency pins pass an
isolated import probe. A missing offline bootstrap fails without running the
requested payload.

Nested legacy test homes require one explicit, owned temporary root. The normal
single-home gate remains unchanged. The maintained fixtures withhold real
credentials. Shared admission rejects the supported provider-token variables and
auth-store paths outside the temporary root, including default-store and nested
credential-file links; 1Password execution targets must
also remain inside that root. The original hook telemetry failure probes admit
only the unavailable loopback endpoint in their explicitly selected fixture mode.
These are admission controls for the reviewed fixtures, not an operating-system
sandbox for arbitrary caller code. No live installation or remote request is
authorised by a passing local test.

### Hook-copy integration boundary

The accepted source revision installs `hooks.json` as a symlink; the separate
hook migration requires a validated regular-file copy. Its publisher, installer,
projection map, validator, complete hook handlers and consent generation must
move as one reviewed integration. Do not mix a copy manifest with the old
symlink validator, or install a manifest without its handlers.

Before enabling that route, prove validation before replacement, source/target
identity checks, recoverable replacement, unchanged-file idempotence, full event
coverage, stale-consent rejection and preservation of sessions and auth. Machine
launcher paths and consent remain local inputs. Existing accepted consent cannot
be reused automatically after changing launcher paths.

The reviewed, uncommitted publisher and complete manifest have been imported
as a content-hash-bound snapshot without changing the other owner's files.
`codex/templates/hook-copy-provenance.json` records this source status explicitly;
it is not an accepted upstream commit. The inactive publisher supports the
complete approved event manifest, validates it before replacement, retains
displaced files and requires a separate regular runtime copy. The validator now
agrees with that copy contract and rejects shared source/runtime inodes.
Its target must remain in the explicit disposable home. Tests cover conversion
from a symlink, repeat/check, rejection and sentinel preservation.

### Handler port and runtime discovery

`codex/hooks/` contains all 16 shell handlers/helpers from the accepted source
revision. Their runtime dependency closure includes command parsing, approval
policy, readiness receipt verification, project metadata, startup maintenance,
configuration repair and the 1Password auth wrapper. Source digests and
transformations are recorded in `codex/templates/handler-provenance.json`;
`scripts/check-source.py` verifies candidate digests and dependency pins.
`requirements/codex-validation.txt` records the existing pinned Python packages;
this migration does not install them or run an online bootstrap.

The inactive handlers require an explicit disposable home and copies of their
code inside it. Admission checks filesystem resources before running the original
guard logic. Outside paths and telemetry endpoints are rejected. A private
machine-specific project-config exception is an optional local fixture input,
`DOTS_PROJECT_CONFIG_EXCEPTION`; it has no default public path. The original
exception validator still applies. Sessions, auth, receipts and caches remain
local; no private state is packaged here.

Admission also checks existing nested resource paths, so default log leaves,
writer-health receipts, deduplication markers and runtime cards cannot follow
pre-existing symlinks outside the fixture. `TMPDIR` must explicitly name a
directory inside that home; validation caches cannot fall back to shared `/tmp`.
Mutable output directories cannot be symlinks, including links whose first
target is inside the fixture. Only exact copied-code/resource links for hooks,
scripts, instructions, schemas, rules and model catalogs are admitted there.
Read-only input trees and temporary fixture containers support in-root aliases;
their resolved children are inspected too, so a second link cannot escape the
resource scan. Event input paths retain the original canonicalisation tests.
This admission check does not establish safety against concurrent hostile
filesystem changes.

`tests/test_hook_handlers.py` invokes real handlers with synthetic events. It
checks safe commands, denied auth access and hook bypasses, explicit commit
approval, missing readiness receipts, lifecycle receipts, startup maintenance
and Stop/prompt safety decisions. Shell syntax is checked for every ported
shell file. Fixture auth, session and database sentinels must remain unchanged.

To run actual app-server discovery, supply the installed Codex CLI's absolute
path. This command starts a local app-server but no model turn, login, review,
CI job or deployment:

```sh
DOTS_CODEX_BIN=/absolute/path/to/codex python3 -B -m unittest discover -s tests -v
```

Without `DOTS_CODEX_BIN`, the installed-runtime test is visibly skipped. With
it, `tests/test_hook_discovery.py` creates a separate minimal fixture config,
discovers every manifest definition with `hooks/list`, and records only their
fresh hashes through `config/value/write` at `hooks.state`. A fresh server must
recognise that consent. Changing a definition must report modified consent;
removing consent must restore untrusted status. API success alone is not proof
that trust changed. This proves discovery and consent state, not execution of
untrusted hooks or production Braid capture.

Braid uses an inert test launcher. LifeOS's private retriever/data, repository
validation commands, hosted review evidence, 1Password Desktop and secrets remain
external dependencies. The handlers' checks are retained, but these fixtures do
not establish availability of those external systems. Production launcher
bindings, full installed-policy integration and live activation still require a
separately verified cutover. The live Configs gates are unchanged.

### Full generated-policy projection integration

`codex/templates/projection-map.json` defines the closed `full-policy-v1` fixture
route. It covers all eight generated configs, hooks, scripts, the migrated
instructions/schema resources and three declared local model catalogs. Agents
metadata, automations and usage data remain real local directories. Auth,
sessions, history and runtime databases are never projection entries.
This map is staged only by the test fixture; it is not an active live map.

`DOTS_PROJECTION_FIXTURE=full-policy-v1` selects the route in the existing
projector. It requires a matching disposable `HOME`/`DOTS_TEST_HOME`, an isolated
source checkout, explicit Codex scope and target, and the exact closed map.
Preflight validates complete canonical policy, schema/profile/registry resources
and the hook manifest before target writes. First publication uses the existing
snapshot validator and atomic repair primitive. The root config and hook
manifest are separate regular files; profiles and code/resources use exact
canonical symlinks. Repeat/check, missing inputs, invalid policy and symlink
escapes are tested through the real entrypoints. Global shell projection stays
disabled in this route.

Installed-runtime checks load the projected root config with `--strict-config`,
then inspect it through `config/read` and `hooks/list`. Seven standalone profiles
are selected through the native `--profile NAME mcp list --json` metadata route,
with file-only credential storage to avoid the system keychain. This does not
start MCP servers, model turns or hosted work. It proves configuration loading
and isolation settings, not model availability or authenticated execution.

The runtime rejected five original disabled `cua_repl` entries without a
transport. Those entries now use `/usr/bin/false`, matching `oss-local`, while
retaining `enabled=false` and `required=false`. The validator permits only that
exact inert shape; regressions reject enabled/required variants, a shell
transport or extra arguments. The three model catalogs are unchanged accepted
source dependencies. Synthetic marketplace metadata uses valid invented values.
No approval, network, review or other policy setting was loosened.

Integration tests repair drift while preserving valid Desktop presentation and
Computer Use plugin consent. They also inject an exchange failure to verify
last-state and backup preservation, update an owned canonical fixture and roll
it back through reconciliation, and check that projected hooks begin untrusted.
Fresh consent remains an explicit native runtime action and is never imported
from policy bindings or copied from a live config into Git.

Config replacement retains the displaced inode in an adjacent private
`.config.toml.recovery-*` directory, including after a successful repair. The
repair JSON and successful installation result identify `retained_generation_path`;
a failed publication reports its recovery location in the error. A writer with
an already open file handle may still save into that retained generation.
These files are local recovery material, not immutable receipts or Git inputs.
Inspect the active and retained generations before an explicitly authorised
recovery, and keep them until native writers have closed their handles. There
is no automatic rollback or cleanup of a generation exposed at the active
path. A detected publication race fails without a compensating swap; this
preserves recoverable data but cannot guarantee that every concurrent save
remains active. Stop native writers before retrying repair or recovering a
selected generation. Passing readback describes the observed generation only.

Browser/pet assets, external adapters and live cutover remain separate migration
surfaces. Passing this generated-policy integration does not retire Configs
checks or prove that those remaining surfaces have been migrated.

### Public instructions, rules and managed constraints

The complete accepted instruction library and portable `codex/AGENTS.md` are now
in this inactive candidate. The two user-profile documents contain only pointers
to optional local context; their private bodies are excluded. The new
[instruction front door](codex/instructions/README.md) and
[migration scope](codex/instructions/migration-scope.md) distinguish reusable
guidance from source-specific Configs commands. The
[Context ledger and provenance](codex/templates/guidance-provenance.json)
record source/candidate digests and deferred dependencies. Missing Configs
helpers remain blocked lanes; they are not replaced with successful stubs.

Six command-rule templates retain the accepted decisions and examples. Machine
paths are constants substituted through the syntax tree; quotes and spaces
cannot become new rule syntax. Two exact fixed-output auth canaries remain
the only `default.rules` allows. Render strings without installation:

```sh
python3 -B scripts/generate-codex-controls.py --bindings tests/fixtures/governance-bindings.json
```

The managed-requirements template retains the allowed approval/sandbox modes
and two exact MCP identities. The private URL comes from the fixture's canonical
policy and is never placed in public inputs. No administrative policy is
installed: requirements stay in the disposable source fixture and are never
projected into the runtime home or `/etc`.

The closed full-policy fixture now includes global AGENTS, all ported
instructions and the six rule layers. Preflight verifies the exact managed
constraints before any target changes. `tests/test_public_controls.py` runs all
93 accepted native `execpolicy check` cases, verifies quoting, rejects widened
constraints/identities and extra rule layers, and checks local-state preservation.
This classifies command arguments; it never executes those example commands.

Run the full suite with an explicit installed CLI as shown above. Missing
native capability cannot pass the standalone controls validator, and a skipped
native test is not full coverage. The pointer check parses active CommonMark
links and verifies local targets/headings and provenance. It does not contact
external sites, establish hosted review clearance, run Configs aggregates or
prove active session enforcement. The ignored local `codex/FORJAMIE.md` handoff
is excluded from publication and projection.

## Deferred integration

The full configuration policy and validator are available here. Their presence
does not prove a successful live cutover. Preserve the previous source and its
recovery copy until actual native hook execution, local data preservation and
the reconciliation service have been verified on the target machine. Roll back
managed Codex targets with the installation's reviewed state and plan digest;
shell bindings and local helper relocation have separate recovery records.
Workstation certificate integration remains a private local input. No existing
required CI check is retired by this port. Native Ghostty/Zellij parsing and
Linux-hosted staging remain separate verification lanes.
Configs-specific root `.mise.toml` and its lock remain in Configs; they select
that repository's CI tooling rather than workstation defaults.

The CircleCI configuration checks this repository only; it does not replace
Configs' existing checks. Local installation records and recovery artifacts stay
outside this public repository; they are not included in hosted validation.
The validation job installs the already-declared validation dependency pins
before running the suite. It partitions the complete discovered test set across
three small containers; each discovered case runs once in that partitioned suite,
in addition to the three diagnostic regressions repeated on each node.
A failure fails validation. The workflow
keeps the `validate` and `secret-scan` jobs, small resource classes, checksum
verification and both secret scans. Hosted timing must confirm that validation
finishes within the job limit; local partition checks do not establish hosted
or Linux runtime acceptance.

