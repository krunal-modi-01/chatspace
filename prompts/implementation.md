# Implementation Prompt — v1.0.0
**Agent:** `backend-engineer` / `frontend-engineer` / `mobile-engineer` · **Skills:** `backend`/`frontend`, `api-design`, `testing`, `database` · **Output:** code + tests + a diff for review
**Use when:** a scoped task from an approved TSD is ready to build.

**Variables:** `{{TASK}}` `{{TSD_LINK}}` `{{CONTRACT_LINK}}` `{{ACCEPTANCE_CRITERIA}}`

---

Implement: {{TASK}}, per the TSD ({{TSD_LINK}}) and contract ({{CONTRACT_LINK}}). Acceptance criteria: {{ACCEPTANCE_CRITERIA}}.

1. **Orient:** read the relevant existing code and conventions (`.claude/CLAUDE.md`). Reuse existing utilities — do not duplicate. If a suitable implementation exists, extend it.
2. **Build the smallest change** that satisfies the acceptance criteria and matches the contract exactly. Honor idempotency, error handling, and resilience from the TSD.
3. **Write tests first or alongside** (`testing` skill): happy path, boundaries, error/failure paths. Cover the acceptance criteria.
4. **Run** lint, typecheck, and tests (commands from `CLAUDE.md`). Fix until green — never report done on red.
5. **Self-check** against the `code-review` lens before handing off; keep the diff focused.
6. Respect hooks: no secrets (`secret-scan`), satisfy `api-change-guard`/`schema-change-guard` checklists if you touched contracts/schema.
7. Hand the diff to `code-reviewer`. Note anything needing a human 🔒 decision.

Match the surrounding code's style and naming. Do not touch out-of-scope files or `do_not_touch` paths.
