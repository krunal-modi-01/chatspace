# Workflow: Bug Fix Flow (reproduce → ship)

Declarative orchestration for a defect. Emphasis: reproduce first, root cause not symptom, regression guard.

```
BUG REPORT (symptom + repro + logs/trace + ticket)
 │
 ▼ [bug-investigator] ── reproduce deterministically
 │      └─ uses monitoring MCP (traces/errors) + git MCP (history/bisect)
 ▼ [bug-investigator] ── write FAILING test (red) ── captures the bug
 ▼ [bug-investigator] ── root-cause (5 whys / bisect)
 ▼ FIX  ── routed to the owning build agent:
 │      [backend-engineer] | [frontend-engineer] | [mobile-engineer]
 ▼ test GREEN + full regression suite
 ▼ [code-reviewer]  ── review the fix
 │      └─ if touches auth/money/PII ─► [security-reviewer] 🔒
 ▼ 🔒 HUMAN REVIEW
 ▼ MERGE ──► (normal) release-flow  |  (urgent) playbooks/hotfix.md
 ▼ MONITOR the fix in prod
 ▼ POSTMORTEM (templates/postmortem.md) ─► knowledge/decisions.md + pipeline improvement
```

## Rules
- **No fix without a reproducing test** — the red→green test is the regression guard and the proof.
- **Root cause, not symptom.** If the true fix is large/risky, ship a safe mitigation behind a flag (🔒) and file the real fix.
- **Emergency path** (`playbooks/hotfix.md`) fast-tracks *ceremony* but never skips the mandatory security gates (`secret-scan`, `vuln-scan`, security-reviewer for auth/money).
- **Every incident produces a lesson** that improves a gate/hook/test so the class of bug can't recur silently.
