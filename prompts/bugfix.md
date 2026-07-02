# Bug Fix Prompt — v1.0.0
**Agent:** `bug-investigator` (→ owning build agent) · **Skills:** `debugging`, `testing` · **Output:** failing test → fix → regression test
**Use when:** a defect needs diagnosis and correction.

**Variables:** `{{SYMPTOM}}` `{{REPRO_STEPS}}` `{{ENV}}` `{{LOGS_OR_TRACE}}` `{{TICKET}}`

---

Diagnose and fix: {{SYMPTOM}} ({{TICKET}}). Repro: {{REPRO_STEPS}}. Env: {{ENV}}. Evidence: {{LOGS_OR_TRACE}}.

1. **Reproduce** deterministically. If you can't, gather what's needed (logs/traces via `monitoring` MCP, `git` history) before changing anything.
2. **Write a failing test** that captures the bug (red). This is the regression guard.
3. **Isolate** the cause: bisect / binary-search the change or code path. Form a hypothesis, test it, iterate. Find the **root cause** (5 whys), not just the symptom.
4. **Fix minimally** at the root cause. Avoid opportunistic refactors in the same change.
5. Turn the test **green**; run the full suite for regressions.
6. Route through `code-reviewer`; if the bug touched auth/money/PII, also `security-reviewer`.
7. Note the root cause + prevention idea for the postmortem / `knowledge/decisions.md`.

Do not paper over the symptom. If the true fix is large/risky, ship a safe mitigation behind the 🔒 gate and file the real fix.
