# Workflow: Feature Flow (idea → production)

Declarative orchestration for delivering a feature. Stages, owning agents, gates.

```
IDEA
 │
 ▼ [product-manager]  ── PRD ──────────────────────────► 🔒 PM approval
 ▼ [business-analyst] ── functional spec
 ▼ [architect]        ── TSD + ADRs ───────────────────► 🔒 architecture approval
 ├─▶ [api-reviewer]    ── API contract           (parallel design)
 └─▶ [database-engineer]── data model + migration
 ▼ TASK BREAKDOWN  (architect + PM)  ── task list
 ▼ IMPLEMENT  (parallel per task, worktree-isolated)
 │   [backend-engineer] | [frontend-engineer] | [mobile-engineer] | [infrastructure-engineer]
 ▼ AUTO-REVIEW  (per task, as each finishes)
 │   [code-reviewer] ──findings──► [author agent] fixes
 ▼ VERIFY  (parallel)
 │   [qa-engineer] tests · [security-reviewer] 🔒 · [performance-engineer] · [accessibility-auditor]
 ▼ [documentation-writer] ── docs updated
 ▼ 🔒 HUMAN REVIEW  (final judgment on the whole change)
 ▼ MERGE  (protected branch, all gates green)
 ▼ [release-manager] + [devops-engineer] ── 🔒 deploy approval ──► canary → phased → full
 ▼ MONITOR  (post-deploy watch; [performance-engineer]/[devops-engineer])
 ▼ PRODUCTION FEEDBACK ──► backlog / knowledge/
```

## Gate summary
| Gate | Owner | Blocks until |
|------|-------|--------------|
| 🔒 PM approval | human PM | requirements agreed |
| 🔒 Architecture | human architect/lead | design sound, risks accepted |
| 🔒 Security | security-reviewer + human | no unmitigated HIGH/CRITICAL |
| 🔒 Human review | human reviewer | judgment on correctness/design |
| 🔒 Deploy | release-manager + human | pre-deploy gates pass, approval recorded |

## Parallelism
- Design: `api-reviewer` ∥ `database-engineer` after TSD.
- Implementation: one agent per task, `isolation: worktree` to avoid conflicts.
- Verify: QA ∥ security ∥ performance ∥ a11y — each starts as soon as its input is ready (pipeline, no batch barrier), except security which must clear before the human review gate.
