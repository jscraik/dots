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

Use Python 3.12 or newer in an existing validation environment containing the
pins in `requirements/codex-validation.txt`. The instruction-pointer checker
uses the already-declared `markdown-it-py==4.2.0`. No online bootstrap or new
dependency is added by this migration.

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

Machine admission treats `CODEX_APP_TOOLS_PIPE_PATH` and `CODEX_TECTONIC_PATH`
as unused native app metadata. Migrated handlers do not open or execute these
values, and they add no resource roots or helper-output permissions. Event paths,
all other scoped environment paths and retained-store protections remain
checked. Rehearsals still reject native metadata paths outside their owned home.

## First-machine installation candidate

`scripts/install-codex.py` provides one local procedure: `prepare`, `apply`,
`check` and `rollback`. It reuses the existing projector, full policy validator,
Desktop-setting preservation and atomic config/hook publishers. It installs no
packages, starts no background service and does not contact a provider or CI.

Preparation creates a private, read-only policy package and validates it before
backing up the 19 managed targets. Config and hook manifests remain independent
regular files; profiles and reusable code use links into that package. Existing
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

For an operator-prepared rehearsal, the command sequence is:

```sh
python3 -B scripts/install-codex.py prepare --mode rehearsal --home TEMP_HOME --state-dir TEMP_HOME/installation/one --bindings BINDINGS_JSON --braid-bin BRAID_BINARY
python3 -B scripts/install-codex.py apply --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
python3 -B scripts/install-codex.py check --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
python3 -B scripts/install-codex.py rollback --state-dir TEMP_HOME/installation/one --plan-digest PREPARED_DIGEST
```

Substitute explicit paths and the digest returned by preparation. That digest
identifies the prepared change; it grants no execution or installation authority.
Do not edit the source or package between commands. Repeated application is a
check; interrupted application resumes before rollback. Unexpected newer target
content stops recovery and retains the backup for inspection.

The candidate also distinguishes the current OS account home from disposable
homes. That admission is not live qualification. A quiet maintenance window,
private binding and external-dependency checks, current consent, independent
review and a separate activation decision are still required. This migration
has not installed into the live home or changed `/etc/codex` policy. Without a
packaged context, all imported tools retain their original strict fixture guard.

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
paths, private endpoint and application identities, consent hashes and personal
Desktop state. Source revision and file digests are in
`codex/templates/policy-provenance.json`. JSON is the source format for this
candidate; generated output is TOML. Comments are not reproduced.

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
governance validation before installation. Never supply credentials as bindings.

The synthetic bindings are invented strings for serialization testing, not
working endpoints, valid hook consent or a deployable workstation configuration.
Private reconstruction was compared against the accepted source: all eight
parsed policies matched before the integration adaptation below. The template
also retains the newer draw.io registration. Its source path and additional
hook-consent identities and hashes use local slots with synthetic examples;
they are not public machine state. Inspect the exact hook definitions and
establish current consent before activation. The reviewed disabled-transport
adaptation remains in place.
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
it back through reconciliation, and check that fresh native hook consent can be
carried in that fixture's canonical input across projection and restart. They
never grant a runtime-only consent exception or copy a live config into Git.

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
The dormant validation job installs the already-declared validation dependency
pins before running the suite. Its two jobs and small resource classes are
unchanged. No hosted job or Linux runtime acceptance is established locally.

