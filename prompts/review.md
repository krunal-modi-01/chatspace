# Review Prompt — v1.0.0
**Agent:** `code-reviewer` · **Skills:** `code-review`, `security`, `testing`, `performance` · **Output:** ranked findings + verdict
**Use when:** a diff is ready for review (post-implementation, pre-merge).

**Variables:** `{{DIFF_OR_PR}}` `{{INTENT}}` `{{TICKET}}`

---

Review the diff ({{DIFF_OR_PR}}). Stated intent: {{INTENT}} ({{TICKET}}).

Review **only** the diff and the code it touches (load definitions on demand). For each finding provide:
- `file:line`
- one-line statement of the defect
- a **concrete failure scenario** (inputs → wrong result). If you can't construct one, label it *unverified*.
- a suggested fix
- severity: **blocker / major / minor / nit**

Cover these lenses: correctness & edge cases, error handling, security (auth/input/secrets), concurrency/resources, tests (do they exercise the change?), and **reuse** (does this duplicate an existing utility?).

Separate correctness/security bugs from style. Be terse — no praise, no restating code. End with:
- **Verdict:** approve / request-changes
- **Top 3** things a human reviewer should focus on.

Do not approve code whose tests are red. Route security findings to `security-reviewer`, perf to `performance-engineer`. Never self-merge — the 🔒 human review gate is final.
