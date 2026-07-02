# Refactoring Prompt — v1.0.0
**Agent:** `refactoring-specialist` · **Skills:** `refactoring`, `testing` · **Output:** behavior-preserving diff
**Use when:** improving structure/readability/debt without changing behavior.

**Variables:** `{{TARGET}}` `{{SMELL_OR_GOAL}}` `{{RISK_LEVEL}}`

---

Refactor {{TARGET}} to address {{SMELL_OR_GOAL}}. Risk level: {{RISK_LEVEL}}.

1. **Establish a safety net first:** confirm tests cover the current behavior. If coverage is thin, add characterization tests **before** refactoring.
2. Refactor in **small, behavior-preserving steps**; run tests after each. For large refactors use **strangler-fig** (introduce the new path, migrate callers incrementally, remove the old).
3. **Change structure, not behavior** — no functional changes mixed in. If you find a bug, note it separately for `bug-investigator`; don't fix it here.
4. Keep the diff reviewable; prefer several small PRs over one large one.
5. Verify: full suite green, no public contract/API change (or route via `api-reviewer` if intended).
6. Hand to `code-reviewer`.

Never refactor and change behavior in the same commit. If risk is high, ship behind a flag with a 🔒 gate.
