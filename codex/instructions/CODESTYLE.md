# CODESTYLE.md

## Purpose

This is the standards front door for dots and its portable Codex guidance.
Dots owns its current process. Imported Configs recipes are historical source
references, not additional prerequisites for work in dots or another project.
Use the active repository's executable commands; this file grants no deployment
or live installation authority.

## Baselines

- Prefer the smallest coherent change that satisfies the named outcome.
- Keep boundaries explicit: validate external data, preserve error states,
  isolate side effects and make replacement/recovery safe.
- Match existing language and framework conventions. Choose abstractions for
  demonstrated responsibilities or repeated variation, not to satisfy a pattern.
- Use strong types where they prevent concrete mistakes. Do not add dependencies,
  wrappers, schemas or classes solely to satisfy a style preference.
- Use comments to explain intent and constraints. A TODO is not itself a release
  defect; unfinished required behaviour, fabricated results and misleading
  completion claims are.
- Review correctness, security, maintainability and real behaviour. Leave
  deterministic formatting and mechanical checks to the configured tools.

## Toolchain configuration

[Workstation pins](../../mise/config.toml) and their
[lock](../../mise/mise.lock) own workstation versions. Dots validation uses
Python 3.12 or newer and the existing dependencies in
[requirements/codex-validation.txt](../../requirements/codex-validation.txt).
The [CI definition](../../.circleci/config.yml) owns its Linux tool versions.

There is no dots package.json, pnpm aggregate, Biome configuration or configured
Pyright gate. Do not run imported package commands or claim those gates exist.
For another repository, read its own manifest, lockfile and configured checks.
A newer upstream release alone is not a reason to change a working pin; update
when compatibility, support or a relevant fix requires it, with focused proof.

## Engineering judgement coverage

Use the task-selected language module for useful conventions, subject to this
front door and the active repository contract. Imported references to Configs
package gates, source paths and source-only skills do not create dots gates.
A module's MUST is scoped to its named technology and configured consumer.

When a convention is unconfigured or inapplicable, record that fact if it matters;
do not invent a waiver ticket or install a tool to satisfy copied prose.
A deliberate exception to a real safety or release control still needs its
owning authority, rationale and appropriate proof.

## Command scope

Run dots commands from the dots repository root. The
[local validation contract](../../README.md#local-checks) is the command authority.
Use an already provisioned validation environment. If a runtime manager refuses
an untrusted checkout, diagnose the trust boundary; do not label it a code failure
or alter machine trust without authority.

Imported Codex helpers may require a disposable fixture. Use their owning tests;
file presence does not make a helper an unrestricted live command.

## Codestyle modules

The [module index](codestyle/README.md) routes language-specific references.
Read only what the task needs. Common routes:

- [Foundations](codestyle/01-foundations.md)
- [Python](codestyle/07-python.md) and [shell](codestyle/10-shell-bash-zsh.md)
- [Security](codestyle/16-security.md)
- [Testing](codestyle/17-testing.md)
- [Development workflow](codestyle/19-development-workflow.md)

## Enforcement model

Run the narrowest proving check first, then the required affected checks.
The dots baseline is:

- `python3 -B -m unittest discover -s tests -v`
- `ruff check --no-cache .`
- `python3 -B scripts/check-source.py`
- `python3 -B scripts/check-public-guidance.py`
- `bash -n scripts/resolve-homebrew-bin.sh`
- `gitleaks dir --no-banner --redact --log-level error .`

Select `bash scripts/test-app-codex.sh` for Desktop runtime proof. Direct unittest
runs without an explicit CLI skip native cases; report that limit. Linux CI and
Desktop proof are different lanes. Focused tests are useful during development;
they do not replace the full suite when claiming the complete validation lane.

For guidance-only edits, source/link checks and review normally suffice; run
behaviour tests when executable guidance or a gate contract changes. A passing
aggregate covers its unchanged components. Repeat only after relevant changes
or an unresolved failure. Use `Command: <exact command> -> pass|fail|blocked
(<reason>)`, with cwd when ambiguous.

## How to use this pack

Start here, select the needed module, and use the active project's check contract.
Update the owning passage when it conflicts with implementation. Keep history in
provenance and task records rather than adding another mandatory instruction layer.
