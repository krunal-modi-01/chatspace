# Documentation Prompt — v1.0.0
**Agent:** `documentation-writer` · **Skills:** `documentation`, `adr-authoring` · **Output:** updated docs / ADR / KB entry
**Use when:** behavior changed, a decision was made, or onboarding/runbook docs need updating.

**Variables:** `{{SUBJECT}}` `{{AUDIENCE}}` `{{CHANGE}}` `{{DOC_TYPE}}`

---

Document {{SUBJECT}} for {{AUDIENCE}}. Change: {{CHANGE}}. Doc type: {{DOC_TYPE}} (README / API / runbook / ADR / KB).

1. **Identify the audience and their goal** — write to what they need to do, not everything you know.
2. Choose the right home: user/dev README, API docs (from the contract), a **runbook** (ops steps), an **ADR** (`templates/adr.md`) for a decision, or `knowledge/` for durable domain knowledge.
3. **Doc-as-code:** keep docs next to what they describe; update them in the same change as the behavior (prevents drift). Include a runnable example where it helps.
4. Be accurate and current — verify commands/examples actually work. Prefer diagrams for structure/flow.
5. For decisions, capture **context → decision → consequences**; add to the ADR index.
6. Cross-link related docs; remove anything now wrong.

Don't document what the code/tests already make obvious; capture the **non-obvious** (why, trade-offs, gotchas). Never include secrets/PII.
