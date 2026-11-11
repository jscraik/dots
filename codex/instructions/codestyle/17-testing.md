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

1. Write a failing test (RED).
2. Implement the smallest change to pass (GREEN).
3. Refactor safely while keeping tests green (REFACTOR).

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
- Use the shared Configs validation contract in [CODESTYLE.md](../CODESTYLE.md#enforcement-model); a passing aggregate covers its unchanged components.

## Enforcement

- Testing evidence MUST list exact commands and outcomes.
- Blocked test steps MUST include concrete blocker reasons.
