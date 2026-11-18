# Validation and Checks

## Table of Contents

- [Standard checks](#standard-checks)
- [Required Check Parity](#required-check-parity)
- [Canonical validator contracts](#canonical-validator-contracts)
- [Command preflight](#command-preflight)
- [Verification default](#verification-default)
- [Quality assurance](#quality-assurance)
- [Path and file verification](#path-and-file-verification)
- [Deterministic toolchain lock](#deterministic-toolchain-lock)

## Standard checks

Read the active repository's AGENTS and validation contract. Dots uses the
commands in [README local checks](../../../README.md#local-checks) and the
[CODESTYLE front door](../CODESTYLE.md). It has no pnpm lint/typecheck/test
pipeline. Retained Configs helpers and their source-only skills do not become
dots prerequisites merely because they are present in the library.

## Required Check Parity

Dots currently declares `validate` and `secret-scan` in
[CircleCI](../../../.circleci/config.yml). Hosted required-check settings must
be inspected separately; a workflow file does not prove branch protection.
Other projects use their own configured GitHub Actions or CircleCI jobs.

## Canonical validator contracts

Use each repository's documented aggregate when it covers the changed scope.
Do not substitute command names from another project or require missing skills.
The imported [validator contracts](../validator-contracts.md) describe their
source consumers; follow them only where the active project adopts them.

## Command preflight

Use the configured non-login shell and invoke shell scripts with `bash`.
Check the relevant root, paths and dependencies for path-sensitive work.
Missing prerequisites block only dependent checks. Do not repeatedly invoke a
failing startup layer when an existing, supported interpreter is available.
Do not change tool trust or bypass a hook to make a check pass.

## Verification default

Run the narrowest meaningful regression check first. Run the active repository's
required baseline once for the final candidate; repeat only after a relevant
change, failure or uncovered risk. An aggregate covers its recorded components.
Record exact commands and `pass`, `fail` or `blocked` outcomes.

## Quality assurance

Prose corrections need source/link/editorial checks. Changes to operational
instructions need contract checks. Hook, projection and installer changes need
disposable-home tests, protected-state preservation and the applicable native
runtime check. Follow the dots app wrapper in README for Desktop proof.

Runtime unavailability blocks that acceptance claim, not unrelated local work.
A skipped native test is not runtime success. Linux CLI tests do not prove
macOS Desktop behaviour; local tests do not prove hosted CI or merge readiness.
Investigate a failure before retrying and retain the nearest meaningful fallback.

Diff-size limits apply only when the active repository adopts and enforces them.
An adopted limit must measure the actual PR merge base, including stacked PRs;
do not split a coherent change solely to satisfy an imported arbitrary threshold.

## Path and file verification

Inspect known trusted paths directly. For untrusted paths, destructive work or
publication, verify type and containment under the authorised root. Check that
documented commands and links exist. Keep test homes and generated reports out
of source; never exercise a hook fixture against the caller's live home.

## Deterministic toolchain lock

Dots pins tools in `mise/config.toml` and `mise/mise.lock`, and Python validation
dependencies in `requirements/codex-validation.txt`. Keep each configured pin
and lock consistent using the owning project's tooling. Other repositories may
adopt a harness contract; its existence elsewhere is not a prerequisite here.
