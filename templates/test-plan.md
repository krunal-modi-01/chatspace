# Test Plan — <Feature Name>

> Owner: `qa-engineer`. Skill: `testing`. Traces to acceptance criteria in the functional spec.

## 1. Scope & strategy
What's tested and at which levels (unit / integration / contract / E2E / non-functional).

## 2. Test matrix
| ID | Traces to (AC / Fn) | Level | Scenario | Expected result | Automated? |
|----|---------------------|-------|----------|-----------------|-----------|
| T1 | AC1 | Unit | happy path | | Yes |
| T2 | AC1 | Unit | boundary/invalid | | Yes |
| T3 | F2 | Integration | dependency down | graceful degrade | Yes |
| T4 | journey | E2E | critical path | | Yes |

## 3. Non-functional tests
- **Performance:** load profile, p95 target, tool.
- **Security:** authZ/IDOR, injection payloads, `security` skill checks.
- **Accessibility:** WCAG 2.2 AA / axe (if UI).

## 4. Test data & environments
Fixtures, seed data, isolation strategy, ephemeral env/testcontainers.

## 5. Entry / exit criteria
- **Entry:** code complete, builds, unit tests pass.
- **Exit (Definition of Done):** all matrix tests pass, no open blockers, coverage-of-behavior adequate, non-functional targets met.

## 6. Risks & gaps
What is intentionally NOT tested and why.
