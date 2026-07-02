# Playbook: Bug Fix (non-emergency)

> Disciplined defect resolution: reproduce, find the true root cause, lock it in with a
> failing test, fix, guard against regression, review, ship. For a production emergency that
> can't wait for full review, use `hotfix.md` instead.

## When to use
- A confirmed defect that is **not** actively causing a production incident.
- Behaviour deviates from the spec, an ADR, or a reasonable user expectation.
- If the bug is causing customer-facing outage/data loss → go to `incident-response.md` first
  (mitigate), then return here (or `hotfix.md`) for the durable fix.

## Preconditions
- A ticket exists with a description and, ideally, reproduction steps (`issue-tracker` MCP).
- You can reproduce the bug locally or in a safe environment.
- `main` is green and you are branched (`fix/<ticket>-<slug>`).

## Steps

| # | Stage | Agent | Skill | Hooks | MCP | Output |
|---|-------|-------|-------|-------|-----|--------|
| 1 | Reproduce reliably | `bug-investigator` | `debugging` | — | `issue-tracker`, `monitoring`, `browser` | deterministic repro + minimal case |
| 2 | Find root cause (not symptom) | `bug-investigator` | `debugging`, `observability` | — | `git`, `filesystem`, `monitoring` | root-cause statement on the ticket |
| 3 | Write a **failing** test that captures the bug | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | red test reproducing the defect |
| 4 | Implement the minimal correct fix | `backend-engineer` / `frontend-engineer` / relevant engineer | `backend` / `frontend` | `pre-edit-guard`, `secret-scan`, `post-edit-format` | `filesystem`, `git` | fix that turns the test green |
| 5 | Regression sweep | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | full suite green; nearby edge cases covered |
| 6 | Code review | `code-reviewer` | `code-review` | — | `git`, `github` | review resolved |
| 6a | Security review (if fix touches auth/money/PII/input) | `security-reviewer` | `security` | `vuln-scan` | `security-scanner` | clean scan / sign-off |
| 7 | 🔒 **Human PR approval** | *human maintainer* | — | `on-stop-verify` | `github` | approved |
| 8 | Merge & ship | `release-manager` → `devops-engineer` | see `release.md` | `pre-commit`, `vuln-scan`, `pre-deploy` 🔒, `post-deploy` | `github`, `cloud` | deployed |
| 9 | Verify fix in prod & close | `bug-investigator` | `observability` | `post-deploy` | `monitoring`, `issue-tracker` | ticket closed with evidence |

### Discipline notes
- **Step 3 before Step 4, always.** The failing test is the definition of "fixed" and the
  regression guard. If you cannot write a test that fails before the fix, you have not yet
  understood the bug — return to Step 2.
- **Root cause, not symptom (Step 2).** Ask "why" until you reach a cause you can prevent
  class-wide, not just this instance. Record the causal chain on the ticket.
- If the root cause reveals systemic debt, open a follow-up per `tech-debt.md` rather than
  expanding this fix's scope.

## Human 🔒 gates
1. **Step 7 — PR approval.** A human approves the diff; `on-stop-verify` confirms tests ran.
2. **Step 8 — deploy approval** via `pre-deploy` (`DEPLOY_APPROVED_BY`).

## Exit criteria
- The Step-3 test failed before the fix and passes after; it is committed.
- Full test suite and `vuln-scan` green in CI.
- Root cause documented on the ticket; a durable note added to `knowledge/decisions.md` if the
  cause was non-obvious.
- Fix verified in production; ticket closed.

## Rollback
- **Pre-merge:** abandon the branch.
- **Post-deploy regression:** revert the fix commit (`git revert <sha>`), redeploy the previous
  artifact. If the revert reintroduces the original bug and that bug is severe, escalate to
  `incident-response.md`.
- Record the outcome in `knowledge/decisions.md`.
