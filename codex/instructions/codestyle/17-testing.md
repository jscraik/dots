# Testing Standards

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [Scope](#scope)
- [Required test layers](#required-test-layers)
- [TDD default workflow](#tdd-default-workflow)
- [Test quality standards](#test-quality-standards)
- [Coverage and gates](#coverage-and-gates)
- [Enforcement](#enforcement)

## Scope

- This module defines testing standards for implementation and release confidence.

## Required test layers

- Test strategy SHOULD include:
  - Unit tests for core logic.
  - Integration tests for boundary interactions.
  - End-to-end tests for critical user workflows when applicable.

## TDD default workflow

For a behavioural regression, reproduce the failure before the fix when feasible,
then keep that case as regression protection. TDD is a useful technique, not a
requirement to manufacture failing tests for prose, formatting or a refactor
already covered by meaningful tests. Choose proof proportional to the change.

## Test quality standards

- Keep tests deterministic and isolated.
- Use Arrange-Act-Assert structure when practical.
- Name tests by behavior and expected outcome.
- Fix implementation when behavior is wrong; only rewrite tests when assertions are invalid.
- Exercise the real entrypoint and observable behavior for regressions. Cover
  the reported failure and a valid neighboring case, isolate fixtures from
  developer state, and avoid source-string or implementation-as-expected-value
  assertions that can pass while the behavior remains broken.

## Coverage and gates

- Apply coverage thresholds only when the repository defines and measures them; prefer tests that prove the relevant failure boundary over an invented percentage.
- Use the active repository contract routed by [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.
- Evaluate agent workflows with representative successful tasks as well as
  intentional denials. Record false blocks, missed denials, completion quality
  and relevant cost or latency. Fixture/schema validation is not a behavioural
  eval. Use deterministic checks for objective criteria and calibrated human
  judgement for qualitative outcomes; no universal score threshold is implied.

## Enforcement

- Testing evidence MUST list exact commands and outcomes.
- Blocked test steps MUST include concrete blocker reasons.
