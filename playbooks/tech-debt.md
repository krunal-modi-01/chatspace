# Playbook: Technical Debt

> Identify, quantify, prioritize, and pay down technical debt deliberately — under test cover,
> in bounded increments, with a standing budget so it never becomes a crisis.

## When to use
- Recurring friction: slow changes in an area, repeated bugs in the same module, flaky tests.
- A design shortcut recorded in an ADR as "revisit later" has come due.
- Planning a sprint and allocating the debt-paydown budget.
- **Not** for behaviour changes — debt paydown must be behaviour-preserving. If behaviour
  changes, it is a feature (`feature-development.md`) or a fix (`bug-fix.md`).

## Preconditions
- The area under consideration has (or can quickly gain) enough test coverage to refactor safely.
- Debt items are tracked in the issue tracker with an `tech-debt` label.

## Identifying & quantifying

Score each debt item on **impact × effort** and record it on the ticket.

| Dimension | Signals |
|-----------|---------|
| **Impact** (how much it hurts) | Change frequency of the area, bug density, incident linkage, onboarding pain, blocked features, SLO risk |
| **Effort** (cost to fix) | Size of the change, blast radius, test coverage gap, coordination needed |

Prioritize with a simple matrix:

```
                 IMPACT
             low         high
         +-----------+-----------+
  EFFORT |  ignore   |   DO      |   low effort
   low   | (monitor) |  FIRST    |
         +-----------+-----------+
         | decline / | plan &    |   high effort
  high   | avoid     | schedule  |
         +-----------+-----------+
```
- **High impact / low effort** → do first (quick wins).
- **High impact / high effort** → plan into a slice, do incrementally under `migration.md` if large.
- **Low impact** → monitor or decline; record the decision so it isn't re-litigated.

## Steps

| # | Stage | Agent | Skill | Hooks | MCP | Output |
|---|-------|-------|-------|-------|-----|--------|
| 1 | Inventory & score debt items | `architect` + `refactoring-specialist` | `architecture`, `refactoring` | — | `issue-tracker`, `knowledge-base` | scored backlog (impact × effort) |
| 2 | Establish test cover for the target area | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | characterization tests (green) before any change |
| 3 | Refactor in behaviour-preserving increments | `refactoring-specialist` | `refactoring` | `pre-edit-guard`, `secret-scan`, `post-edit-format` | `filesystem`, `git` | smaller, safer diffs; suite stays green |
| 4 | Re-run full suite after each increment | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | no behaviour change; coverage maintained |
| 5 | Review | `code-reviewer` | `code-review` | — | `github` | review resolved |
| 6 | 🔒 **Human PR approval** | *human maintainer* | — | `on-stop-verify` | `github` | approved |
| 7 | Merge & (optionally) ship | `release-manager` | see `release.md` | CI gates | `github` | landed |
| 8 | Record & close | `documentation-writer` | `documentation` | — | `knowledge-base` | ADR update / note in `knowledge/decisions.md` |

### Working under test cover (Step 2 is non-negotiable)
Refactoring without tests is just editing and hoping. Before touching the code, add
characterization tests that pin the *current* behaviour. The refactor is correct only if those
tests stay green throughout. Keep each increment small enough to review and revert on its own.

## Budgeting debt paydown
- Allocate a standing fraction of each sprint (commonly **10–20%**) to debt from the scored
  backlog, highest impact-per-effort first.
- Treat the budget as a ratchet: unused debt budget does not roll into feature work — protecting
  it is how debt stays bounded.
- Link paid-down items back to the ADRs or incidents that motivated them.

## Human 🔒 gates
1. **Step 6 — PR approval.** As with any change, a human approves; `on-stop-verify` confirms the
   suite ran and stayed green.

## Exit criteria
- Targeted debt item resolved; behaviour provably unchanged (tests green before and after).
- Coverage in the area is equal or better than before.
- The scored backlog and `knowledge/decisions.md` are updated; superseded ADRs marked.

## Rollback
- Because each increment is small and behaviour-preserving, revert the offending commit
  (`git revert <sha>`) with no user impact.
- If a refactor unexpectedly changes behaviour, it is a bug — stop, revert, and route through
  `bug-fix.md`.
