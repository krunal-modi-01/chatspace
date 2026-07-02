# Playbook: Hotfix (expedited production fix)

> A fast lane for fixing a live production problem. It trades **scope** for speed — the change
> is kept minimal — but it does **not** trade away the mandatory safety gates. Some gates are
> compressed; none marked below as *cannot skip* may be removed.

## When to use
- Production is broken or degraded and the fix cannot wait for the normal `bug-fix.md` cadence.
- The change is small and surgical (one focused fix), not a refactor or feature.
- If the system is actively on fire (outage, data loss, SEV1/2), run `incident-response.md`
  **first** to mitigate (feature flag, rollback, rate limit), then use this playbook for the
  durable fix once the bleeding has stopped.

## Preconditions
- An incident/ticket exists and the impact and severity are recorded.
- A named human approver is available for the emergency gate.
- You branch from the **currently deployed** release tag, not from `main` if `main` has drifted
  ahead — the hotfix must be minimal relative to what is live. Branch name: `hotfix/<ticket>-<slug>`.

## Steps

| # | Stage | Agent | Skill | Hooks | MCP | Cannot skip? |
|---|-------|-------|-------|-------|-----|:---:|
| 1 | Confirm impact & smallest possible fix | `bug-investigator` | `debugging` | — | `monitoring`, `issue-tracker` | — |
| 2 | Minimal-change branch from the live tag | `release-manager` | `git` | — | `git`, `github` | — |
| 3 | Failing test for the specific defect | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | ✅ (at least one) |
| 4 | Apply the minimal fix | relevant engineer | `backend` / `frontend` | `pre-edit-guard`, `secret-scan`, `post-edit-format` | `filesystem`, `git` | **secret-scan ✅** |
| 5 | Fast-track review | `code-reviewer` | `code-review` | — | `github` | ✅ |
| 6 | **Security review** — required if the fix touches auth, authorization, money, PII, or secrets | `security-reviewer` | `security` | `vuln-scan` | `security-scanner` | **✅ for auth/money/PII** |
| 7 | Dependency/SAST scan | (CI) | — | `vuln-scan` | `security-scanner` | **✅** |
| 8 | 🔒 **Emergency deploy approval** | *human approver* | — | `pre-deploy` | `github` | **✅** |
| 9 | Deploy (expedited canary, then promote) | `devops-engineer` | `observability` | `pre-deploy`, `post-deploy` | `cloud`, `kubernetes` | — |
| 10 | Verify recovery | `bug-investigator` | `observability` | `post-deploy` | `monitoring` | ✅ |
| 11 | **Backport to `main`** and any active release branches | `release-manager` | `git`, `migration` | `pre-commit` | `git`, `github` | **✅** |
| 12 | Schedule follow-up & postmortem if SEV | `bug-investigator` | `documentation` | — | `issue-tracker` | — |

### Gates that CANNOT be skipped, ever
Even under time pressure the following remain mandatory (enforced by hooks, not convention):
- **`secret-scan`** — `PostToolUse` on every edit; exits 2 and blocks on a leaked credential.
- **`vuln-scan`** — no HIGH/CRITICAL SCA/SAST findings may ship (`pre-deploy` re-runs it).
- **`security-reviewer` sign-off** — required whenever the fix touches authentication,
  authorization, money movement, or PII. "It's urgent" is not an exemption.
- **`pre-deploy` human approval** — `DEPLOY_APPROVED_BY` must be set by a real person.

What *is* compressed: design docs, broad regression sweeps, performance/accessibility passes,
and full documentation — these are deferred to the Step-11/12 follow-up, not skipped forever.

## Human 🔒 gates
1. **Step 8 — emergency deploy approval.** A single named approver may authorize, but it must be
   a human and it is logged (`DEPLOY_APPROVED_BY`). The identity is recorded for the postmortem.

## Exit criteria
- Production impact is resolved and confirmed via `monitoring`.
- The failing test passes; `secret-scan` and `vuln-scan` are clean; security sign-off obtained
  where required.
- The fix is backported to `main` (and release branches) so it is not lost on the next deploy.
- A follow-up ticket exists for the deferred work; a postmortem is scheduled if this was a SEV.

## Rollback
- Hotfixes are the fastest thing to roll back: redeploy the previous release tag (the one you
  branched from) or flip the feature flag. `post-deploy` failure signals rollback is needed.
- If rollback reintroduces the outage, escalate to `incident-response.md` and mitigate by other
  means (traffic shed, dependency circuit-break).
- Log the rollback and root cause in `knowledge/decisions.md` and the postmortem
  (`templates/postmortem.md`).
