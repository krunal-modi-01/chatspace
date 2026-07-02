---
name: testing
description: Test strategy and generation across unit, integration, contract, E2E, and non-functional tests. Use when writing tests, deciding what to test, reviewing test adequacy, or setting up a project's test approach. Stack-agnostic — detects the test runner from the project.
---

# Testing Skill

## Purpose
Produce tests that give real confidence — testing behavior and contracts, not implementation detail — at the right level of the pyramid, cheaply and deterministically.

## When invoked
Writing tests for a change; assessing whether a diff is adequately tested (used by `code-reviewer` and `qa-engineer`); designing a project's test strategy; reproducing a bug as a failing test (used by `bug-investigator`).

## Inputs
The code/behavior under test, the spec/acceptance criteria, existing tests + fixtures, the test command (`CLAUDE_TEST_CMD` / auto-detected).

## Outputs
New/updated tests, a coverage-of-behavior assessment (not just % lines), and a note on gaps (what's still untested and why).

## The pyramid (target distribution)
| Level | Scope | Speed | Share | Use for |
|-------|-------|-------|-------|---------|
| Unit | one function/class, no I/O | ms | ~70% | logic, edge cases, error paths |
| Integration | module + real deps (DB, queue) | 10s–s | ~20% | wiring, queries, transactions |
| Contract | API producer/consumer | fast | as needed | every external API boundary |
| E2E | full system via UI/API | slow | ~10% | critical user journeys only |
| Non-functional | load, security, a11y | varies | targeted | SLAs, `performance`/`security` skills |

## Procedure
1. **Derive cases from behavior & spec**, not from the implementation. Cover: happy path, boundaries, empty/null, invalid input, error/failure of dependencies, concurrency where relevant.
2. **Pick the lowest level** that can catch the failure. Don't E2E what a unit test covers.
3. **Make tests deterministic:** control time/randomness/network; no sleeps — poll/await; isolated data per test.
4. **Arrange-Act-Assert**, one behavior per test, descriptive names (`does_X_when_Y`).
5. **Assert on outcomes**, not internals — refactors shouldn't break good tests.
6. **For bugs:** write the failing test first (red), then fix (green), keep it as a regression test.

## Best practices
- Test behavior and contracts; avoid asserting on private state or call counts unless that *is* the contract.
- Prefer real dependencies in integration tests (testcontainers/ephemeral DB) over deep mocking.
- Coverage is a floor signal, not a goal — 100% lines with weak asserts proves nothing.
- Keep the suite fast; quarantine flaky tests, don't retry-hide them.

## Anti-patterns
- Snapshot-everything tests that break on any change. · Mocking the thing under test. · Tests that pass when the code is deleted. · Non-deterministic tests kept green with retries. · E2E for logic that a unit test covers.
