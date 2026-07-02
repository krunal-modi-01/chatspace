# Playbook: Release

> Cut, ship, and verify a release. Owned by the `release-manager`, executed with the
> `devops-engineer`. Applies to a scheduled release train or a batched set of merged changes.

## When to use
- A set of changes on `main` is ready to promote to production.
- Cutting a versioned release (tag + notes), whether time-based (every sprint) or on-demand.
- For a single urgent production fix, use `hotfix.md` (which reuses the deploy gates below).

## Preconditions
- `main` is green: lint, typecheck, tests, and `vuln-scan` all passing in CI.
- All changes intended for the release are merged; a code freeze window is agreed.
- The previous release tag is known (needed for the diff, notes, and rollback target).

## Steps

| # | Stage | Agent | Skill | Hooks | MCP | Output |
|---|-------|-------|-------|-------|-----|--------|
| 1 | **Freeze** — stop merging non-release changes to the release line | `release-manager` | `git` | — | `github` | frozen branch/commit |
| 2 | Determine version (SemVer) | `release-manager` | `git` | — | `git` | `vX.Y.Z` chosen |
| 3 | Generate release notes | `release-manager` | `documentation` | — | `git`, `github`, `issue-tracker` | `templates/release-notes.md` filled |
| 4 | Build & publish artifact | `devops-engineer` | `docker` | `pre-commit` (CI) | `docker`, `cloud` | immutable, versioned artifact |
| 5 | 🔒 **Pre-deploy gate** | *human approver* + CI | — | `pre-deploy` | `security-scanner` | approval recorded, `vuln-scan` clean, tests green |
| 6 | Canary / phased rollout | `devops-engineer` | `observability` | `pre-deploy`, `post-deploy` | `kubernetes`, `cloud`, `monitoring` | small % of traffic on new version |
| 7 | Watch canary | `devops-engineer` + `performance-engineer` | `observability`, `performance` | `post-deploy` | `monitoring` | error rate & latency within SLO |
| 8 | Promote to 100% | `devops-engineer` | `observability` | `post-deploy` | `kubernetes`, `cloud` | full rollout |
| 9 | Post-deploy watch | `devops-engineer` | `observability` | `post-deploy` | `monitoring` | SLOs healthy for the watch window (e.g. 30m) |
| 10 | **Tag** the release & unfreeze | `release-manager` | `git` | — | `git`, `github` | annotated tag `vX.Y.Z` pushed; freeze lifted |
| 11 | Record decision | `documentation-writer` | `documentation` | — | `knowledge-base` | row in `knowledge/decisions.md` |

### Versioning (SemVer)
- **MAJOR** — breaking API/contract change (coordinate with `api-reviewer`; note in release notes).
- **MINOR** — backward-compatible feature.
- **PATCH** — backward-compatible fix.
- Pre-release/canary builds may carry a suffix (e.g. `vX.Y.Z-rc.1`).

### Rollout strategy
- **Canary first** (Step 6): route a small slice of traffic to the new version and hold.
- **Automatic abort:** if `post-deploy` healthchecks fail or `monitoring` shows SLO breach
  during the canary, do **not** promote — roll back (see below).
- **Phased promotion:** widen (e.g. 5% → 25% → 100%) only while metrics stay green.

## Human 🔒 gates
1. **Step 5 — pre-deploy approval.** `pre-deploy.sh` exits non-zero unless `DEPLOY_APPROVED_BY`
   is set by a human, `vuln-scan` is clean, and `TESTS_GREEN=true`. This gate guards *both*
   canary and full promotion.

## Exit criteria
- Release deployed to 100% and healthy through the watch window.
- Annotated tag `vX.Y.Z` pushed; release notes published.
- No open SEV incidents attributable to the release.
- Decision logged in `knowledge/decisions.md`.

## Rollback
- **During canary:** stop the rollout and redeploy the previous tag; canary carries minimal blast
  radius by design.
- **After promotion:** redeploy the previous known-good tag (blue/green swap or `kubectl rollout
  undo` / equivalent). `post-deploy.sh` returning non-zero is the signal to roll back.
- **Data/schema in the release:** if the release included an irreversible schema change, roll back
  per the expand-contract plan in `migration.md` — never drop a column to roll back a deploy.
- If rollback does not restore health, escalate to `incident-response.md`.
- Record the rollback, cause, and version in `knowledge/decisions.md`.
