# Testing Prompt — v1.0.0
**Agent:** `qa-engineer` · **Skills:** `testing` · **Output:** tests + `templates/test-plan.md` + gap note
**Use when:** generating tests for a change or assessing test adequacy.

**Variables:** `{{TARGET}}` `{{ACCEPTANCE_CRITERIA}}` `{{EXISTING_TESTS}}`

---

Produce/assess tests for {{TARGET}} against acceptance criteria {{ACCEPTANCE_CRITERIA}}. Existing tests: {{EXISTING_TESTS}}.

1. Derive cases from **behavior and acceptance criteria**, not the implementation. Cover: happy path, boundaries, empty/null, invalid input, dependency failure, and concurrency where relevant.
2. Choose the **lowest pyramid level** that catches each failure (unit > integration > E2E). Add a contract test for every external API boundary.
3. Make tests **deterministic**: control time/randomness/network; isolated data; no sleeps.
4. Assert on **outcomes/contracts**, not internals. One behavior per test; descriptive names.
5. Run the suite (command from `CLAUDE.md`); confirm new tests fail without the change and pass with it.
6. Fill `templates/test-plan.md`; include non-functional needs (perf/security/a11y) and a **gap note** of what's intentionally untested.

Coverage % is a floor, not the goal — prioritize behavior coverage. Quarantine flaky tests; never hide them with retries.
