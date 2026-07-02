# Planning Prompt — v1.0.0
**Agent:** `product-manager` (→ `business-analyst`) · **Skills:** — · **Output:** `templates/prd.md` then `templates/functional-spec.md`
**Use when:** an idea/request needs to become scoped, testable requirements.

**Variables:** `{{IDEA}}` `{{BUSINESS_CONTEXT}}` `{{CONSTRAINTS}}` `{{STAKEHOLDERS}}`

---

You are turning a raw idea into a plan. Idea: {{IDEA}}. Context: {{BUSINESS_CONTEXT}}. Constraints: {{CONSTRAINTS}}.

1. Restate the **problem** and who has it. If the problem is unclear or you're inventing scope, STOP and ask {{STAKEHOLDERS}} up to 3 clarifying questions.
2. Define **goals** (measurable) and explicit **non-goals**.
3. Write **user stories** and, for each, **Given/When/Then acceptance criteria**.
4. Prioritize requirements (MoSCoW). Flag anything with compliance/regulatory impact.
5. List **risks, dependencies, open questions** with owners.
6. Produce output in the shape of `templates/prd.md`. Mark the 🔒 human PM approval gate before design begins.

Be concrete and testable. Do not propose a solution/design — that's the architect's job. Prefer the smallest scope that solves the real problem.
