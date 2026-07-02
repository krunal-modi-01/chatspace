# Playbook: Feature Development

> Full lifecycle for a net-new feature — from problem statement to a monitored production
> deploy. This is the canonical happy-path flow. For a defect see `bug-fix.md`; for an
> expedited production fix see `hotfix.md`.

## When to use
- A new capability, screen, endpoint, or workflow is being added.
- The change is large enough to warrant a spec and design review (roughly: touches more
  than one component, or introduces a new contract, data shape, or user-visible behaviour).
- Not appropriate for one-line fixes or config tweaks — those go through `bug-fix.md`.

## Preconditions
- `.claude/CLAUDE.md` **PROJECT FACTS** are filled in (commands, conventions, boundaries).
- An issue/ticket exists in the tracker (`issue-tracker` MCP) with a rough problem statement.
- `main` is green (CI passing) and you are branched from an up-to-date `main`.
- `session-start` hook has run and surfaced recent decisions from `knowledge/decisions.md`.

## Steps

Each step names the **owning agent**, the **skill** it leans on, the **hooks** that fire, and
the **MCP** servers it reaches for. The main thread orchestrates and delegates; it does not
do every step itself.

| # | Stage | Agent | Skill | Hooks | MCP | Output |
|---|-------|-------|-------|-------|-----|--------|
| 1 | Frame the problem & write the PRD | `product-manager` | `documentation` | — | `issue-tracker`, `knowledge-base` | `templates/prd.md` filled in |
| 2 | Elaborate requirements & acceptance criteria | `business-analyst` | `documentation` | — | `issue-tracker` | `templates/functional-spec.md` |
| 3 | Design the technical approach | `architect` | `architecture`, `adr-authoring` | `pre-edit-guard` | `knowledge-base`, `git` | `templates/technical-spec.md` + ADR(s) in `architecture/adr/` |
| 3a | Review API contract (if any new/changed API) | `api-reviewer` | `api-design` | `api-change-guard` | `openapi` | `templates/api-contract.md` |
| 3b | Design schema changes (if any) | `database-engineer` | `database`, `migration` | `schema-change-guard` | `postgres` | `templates/database-design.md` + migration plan |
| 4 | Break down into tasks | `architect` + `product-manager` | `architecture` | — | `issue-tracker` | ordered task list on the ticket |
| 5 | Implement | `backend-engineer` / `frontend-engineer` / `mobile-engineer` / `infrastructure-engineer` | `backend`, `frontend`, `terraform`, etc. | `pre-edit-guard`, `secret-scan`, `post-edit-format` | `filesystem`, `git`, `docker` | working code + unit tests |
| 6 | Write & run tests | `qa-engineer` | `testing` | `on-test-fail` | `filesystem` | test plan (`templates/test-plan.md`) executed; coverage of new paths |
| 7 | Code review | `code-reviewer` | `code-review` | — | `git`, `github` | review comments resolved |
| 8 | Security review | `security-reviewer` | `security` | `vuln-scan` | `security-scanner` | `templates/threat-model.md` (if auth/money/PII) + clean SCA/SAST |
| 9 | Performance check (if hot path) | `performance-engineer` | `performance`, `observability` | — | `monitoring` | benchmark within budget |
| 10 | Accessibility audit (if UI) | `accessibility-auditor` | `frontend` | — | `browser` | WCAG issues resolved |
| 11 | Documentation | `documentation-writer` | `documentation` | — | `knowledge-base`, `git` | user/API docs + durable note in `knowledge/` |
| 12 | 🔒 **Human review & approval** | *human maintainer* | — | `on-stop-verify` | `github` | PR approved |
| 13 | Merge | `code-reviewer` (assists) | `git` | `pre-commit`, `secret-scan`, `vuln-scan` (in CI) | `github` | merged to `main` |
| 14 | Release & deploy | `release-manager` → `devops-engineer` | see `release.md` | `pre-deploy` 🔒, `post-deploy` | `cloud`, `kubernetes`, `terraform` | deployed (canary → full) |
| 15 | Monitor | `devops-engineer` | `observability` | `post-deploy` | `monitoring` | SLOs healthy for the watch window |

### Notes on key steps
- **Step 3 (design):** the `architect` records every non-obvious trade-off as an ADR using
  `templates/adr.md`, and indexes it in `architecture/adr/README.md`. See `tech-debt.md` if
  the design deliberately incurs debt.
- **Step 5 (implement):** `secret-scan` runs `PostToolUse` on every edit and **blocks (exit 2)**
  on a leaked credential — it cannot be bypassed. `post-edit-format` auto-formats.
- **Step 8 (security):** mandatory whenever the feature touches authentication, authorization,
  money movement, PII, file upload, or external requests. `vuln-scan` must be clean
  (no HIGH/CRITICAL) before the PR can merge.

## Human 🔒 gates
1. **Design sign-off (optional but recommended for large features)** — a human accepts the
   `technical-spec` and ADRs before implementation starts.
2. **Step 12 — PR approval.** No feature merges without a human approving the diff. The
   `on-stop-verify` hook confirms tests were actually run before "done" is claimed.
3. **Step 14 — deploy approval.** `pre-deploy` refuses to run unless `DEPLOY_APPROVED_BY` is
   set by a human (see `release.md`).

## Exit criteria
- Acceptance criteria from the functional spec are demonstrably met.
- CI is green: lint, typecheck, tests, `vuln-scan` all pass.
- Security review complete (or explicitly N/A and recorded on the PR).
- Docs updated; a durable note added to `knowledge/decisions.md` if a non-obvious choice was made.
- Feature deployed and SLOs healthy through the post-deploy watch window.

## Rollback
- **Pre-merge:** abandon the branch; no production impact.
- **Post-merge, pre-deploy:** revert the merge commit on `main` (`git revert -m 1 <sha>`),
  re-run CI.
- **Post-deploy:** follow `release.md` rollback — roll back the canary/release (redeploy the
  previous known-good artifact or flip the feature flag off). If there is user-facing impact,
  escalate to `incident-response.md`.
- Record the rollback and its cause in `knowledge/decisions.md`.
