# CLAUDE.md — Operating Constitution

> This file is loaded into **every** Claude Code session in this project. It is the single source of truth for how work is done here. Keep it short, factual, and current. Agents, hooks, and skills all defer to it. When this file and any other document disagree, **this file wins**.

---

## PROJECT FACTS  *(fill this in per project — everything downstream reads it)*

```yaml
project_name:        <name>
pipeline_version:    1.0.0            # version of claude-pipeline this project tracks
domain:              <e.g. banking / e-commerce / internal tooling>
languages:           [<e.g. TypeScript, Go>]
frameworks:          [<e.g. React, NestJS>]
package_managers:    [<e.g. pnpm, go mod>]

commands:
  install:           <e.g. pnpm install>
  build:             <e.g. pnpm build>
  test:              <e.g. pnpm test>
  test_one:          <e.g. pnpm test -- {path}>
  lint:              <e.g. pnpm lint>
  format:            <e.g. pnpm format>
  typecheck:         <e.g. pnpm typecheck>
  run:               <e.g. pnpm dev>

conventions:
  branch:            <e.g. feat/<ticket>-<slug>, fix/<ticket>-<slug>>
  commit:            <e.g. Conventional Commits>
  pr_target:         <e.g. main via squash>

boundaries:
  do_not_touch:      [<generated dirs, vendored code, migrations already shipped>]
  secrets_location:  <e.g. env vars only; never committed>
```

---

## OPERATING PRINCIPLES

1. **Discover, don't assume.** Read `PROJECT FACTS` and the codebase before acting. Never hardcode a stack assumption.
2. **Least context, right context.** Load only what the task needs (see `docs/08-context-engineering.md`). Prefer delegating a search to a subagent over dumping files into the main thread.
3. **Delegate by role.** Route work to the specialized subagent that owns the phase (see roster below). The main thread orchestrates; it does not do everything itself.
4. **Verify before claiming done.** Run the relevant `commands`. If tests fail, say so with output. Never report success you haven't observed.
5. **Security is non-negotiable.** The secret-scan, vuln-scan, and security-review gates cannot be skipped. Secrets never enter context or logs.
6. **Humans hold the gates.** Propose diffs, plans, and releases; a human approves the checkpoints marked 🔒 in `docs/03-sdlc-flow.md`.

---

## AGENT ROSTER  *(canonical names — do not rename; docs/hooks/prompts reference these)*

| Phase | Agents |
|-------|--------|
| **Plan** | `product-manager`, `business-analyst` |
| **Design** | `architect`, `api-reviewer`, `database-engineer` |
| **Build** | `backend-engineer`, `frontend-engineer`, `mobile-engineer`, `infrastructure-engineer` |
| **Verify** | `qa-engineer`, `code-reviewer`, `security-reviewer`, `performance-engineer`, `accessibility-auditor` |
| **Ship** | `devops-engineer`, `release-manager` |
| **Sustain** | `bug-investigator`, `refactoring-specialist`, `documentation-writer` |

Invoke with: *"Use the `<agent-name>` agent to …"*. Definitions live in `.claude/agents/<name>.md`.

---

## SKILLS  *(auto-invoked by description match; see `.claude/skills/`)*

`architecture` · `backend` · `frontend` · `api-design` · `testing` · `database` · `docker` · `aws` · `terraform` · `kubernetes` · `git` · `code-review` · `debugging` · `logging` · `observability` · `security` · `performance` · `documentation` · `refactoring` · `migration` · `dependency-update` · `prompt-engineering` · `adr-authoring`

---

## MEMORY CONTRACT

- **Long-term** → `knowledge/` (decisions, patterns, glossary). Durable across sessions. Update via the `documentation-writer` agent.
- **Project state** → `architecture/` (ADRs, current diagrams) + issue tracker via MCP.
- **This file** → conventions and facts. Update deliberately, via PR.
- **Session/short-term** → the conversation. Do not persist secrets, PII, or credentials anywhere.

Write a durable note when a **non-obvious** decision is made (a trade-off, a workaround, a constraint). Do not record what the code/git history already shows.

---

## DEFINITION OF DONE

A change is done only when: code compiles · lint + typecheck pass · tests (new + existing) pass · security gates pass · docs updated if behavior changed · a human approved the required 🔒 gate. See `docs/03-sdlc-flow.md`.

---

## GUARDRAILS

- Never commit, log, or echo secrets/tokens/PII. The `secret-scan` hook enforces this; do not disable it.
- Never run destructive commands (`rm -rf`, force-push to protected branches, prod migrations) without explicit human confirmation.
- Never introduce a new dependency without the `dependency-update` skill's vetting checklist.
- Off-host data egress (MCP servers that call external services) is opt-in and listed in `.claude/mcp/mcp.json`. Regulated data must stay on-host unless approved.
