# CLAUDE.md — Operating Constitution

> This file is loaded into **every** Claude Code session in this project. It is the single source of truth for how work is done here. Keep it short, factual, and current. Agents, hooks, and skills all defer to it. When this file and any other document disagree, **this file wins**.

---

## PROJECT FACTS

```yaml
project_name:        chatspace
pipeline_version:    1.0.0
domain:              team-chat / real-time messaging (Slack-style)
languages:           [Python, TypeScript]
frameworks:          [FastAPI, React]
package_managers:    [uv, npm]

commands:
  install:            "cd backend && uv sync"
  build:               "cd frontend && npm run build"
  test:                "cd backend && uv run pytest && cd ../frontend && npm run test"
  test_one:            "cd backend && uv run pytest {path}"
  lint:                "cd backend && uv run ruff check . && cd ../frontend && npm run lint"
  format:              "cd backend && uv run ruff format ."
  typecheck:           "cd backend && uv run mypy app && cd ../frontend && npm run typecheck"
  run:                 "docker-compose up --build"
  migrate_new:         "cd backend && uv run alembic revision --autogenerate -m {message}"
  migrate_up:          "cd backend && uv run alembic upgrade head"

conventions:
  branch:             "feat/<ticket>-<slug>, fix/<ticket>-<slug>"
  commit:             "Conventional Commits"
  pr_target:          "main via squash, 1 approval required"

boundaries:
  do_not_touch:       [alembic/versions/* (never edit a shipped migration, only add new ones), frontend/src/generated/*]
  secrets_location:   "env vars only (.env, never committed); JWT signing key, DB URL, Redis URL, all loaded via pydantic-settings"
```

---

## OPERATING PRINCIPLES

1. **Discover, don't assume.** Read `PROJECT FACTS` and the codebase before acting. Never hardcode a stack assumption.
2. **Least context, right context.** Load only what the task needs. Prefer delegating a search to a subagent over dumping files into the main thread.
3. **Delegate by role.** Route work to the specialized subagent that owns the phase. The main thread orchestrates; it does not do everything itself.
4. **Verify before claiming done.** Run the relevant `commands`. If tests fail, say so with output. Never report success you haven't observed.
5. **Security is non-negotiable.** The secret-scan, vuln-scan, and security-review gates cannot be skipped. Secrets never enter context or logs. Chat messages and user PII are sensitive data — treat them accordingly even at this scale.
6. **Humans hold the gates.** Propose diffs, plans, and releases; a human approves the checkpoints marked 🔒.
7. **Build for 1,000 concurrent users, not 1,000,000.** Prefer a single well-run Postgres + Redis + a couple of app instances over premature horizontal-scaling complexity (no sharding, no message queue cluster, no multi-region). Re-evaluate only when real usage data says so — record that as an ADR, not a guess.

---

## AGENT ROSTER

| Phase | Agents |
|-------|--------|
| **Plan** | `product-manager`, `business-analyst` |
| **Design** | `architect`, `api-reviewer`, `database-engineer` |
| **Build** | `backend-engineer`, `frontend-engineer`, `infrastructure-engineer` |
| **Verify** | `qa-engineer`, `code-reviewer`, `security-reviewer`, `performance-engineer`, `accessibility-auditor` |
| **Ship** | `devops-engineer`, `release-manager` |
| **Sustain** | `bug-investigator`, `refactoring-specialist`, `documentation-writer` |

`mobile-engineer` is unused for now — this is web-only. Re-add if a mobile client is scoped later.

Invoke with: *"Use the `<agent-name>` agent to …"*. Definitions live in `.claude/agents/<name>.md`.

---

## SKILLS

`architecture` · `backend` · `frontend` · `api-design` · `testing` · `database` · `docker` · `git` · `code-review` · `debugging` · `logging` · `observability` · `security` · `performance` · `documentation` · `refactoring` · `migration` · `dependency-update` · `prompt-engineering` · `adr-authoring`

`aws` · `terraform` · `kubernetes` are in the pipeline but **not currently in scope** — deployment target is a single Docker host / small managed platform (Render, Fly.io, Railway — TBD via ADR), not k8s.

---

## MEMORY CONTRACT

- **Long-term** → `knowledge/` (decisions, patterns, glossary). Durable across sessions. Update via the `documentation-writer` agent.
- **Project state** → `architecture/` (ADRs, current diagrams) + issue tracker via MCP.
- **This file** → conventions and facts. Update deliberately, via PR.
- **Session/short-term** → the conversation. Do not persist secrets, PII, or credentials anywhere.

Write a durable note when a **non-obvious** decision is made (a trade-off, a workaround, a constraint). Do not record what the code/git history already shows.

---

## DEFINITION OF DONE

A change is done only when: code compiles · lint + typecheck pass · tests (new + existing) pass · security gates pass · docs updated if behavior changed · a human approved the required 🔒 gate.

---

## GUARDRAILS

- Never commit, log, or echo secrets/tokens/PII. The `secret-scan` hook enforces this; do not disable it. This includes never logging raw message content or JWTs in application logs.
- Never run destructive commands (`rm -rf`, force-push to protected branches, prod migrations) without explicit human confirmation.
- Never introduce a new dependency without the `dependency-update` skill's vetting checklist.
- Off-host data egress (MCP servers that call external services) is opt-in and listed in `.claude/mcp/mcp.json`. User messages and account data must stay on-host unless explicitly approved.

---

## DOMAIN MODEL

- **User** — id, username, email, hashed_password, avatar_url, created_at
- **Channel** — id, name, is_private, created_by, created_at
- **ChannelMember** — channel_id, user_id, role (member/admin), joined_at
- **Message** — id, channel_id (nullable if DM), sender_id, recipient_id (nullable if channel), content, created_at, edited_at, deleted_at (soft delete)
- **DM threads** — data model TBD, see Open Decisions below
- **Presence** — tracked in Redis (online/offline/last_seen), not Postgres — ephemeral, no durability needed

---

## ARCHITECTURE NOTES (1,000-user scale)

- **App servers:** 1–2 FastAPI instances behind a load balancer is sufficient; use Redis pub/sub so WebSocket broadcasts work correctly across more than one instance.
- **Database:** single managed PostgreSQL instance with daily backups; connection pooling via `asyncpg` pool / PgBouncer if connection count becomes an issue — not expected at this scale.
- **Redis:** used for (a) WebSocket fan-out pub/sub, (b) presence, (c) basic rate limiting. A single Redis instance is fine; no cluster.
- **Message delivery:** at-least-once with client-side dedup by message id; no need for exactly-once guarantees or a message queue (Kafka/RabbitMQ) at this scale.
- **Observability:** structured logging (JSON) + a basic uptime/error monitor (e.g. Sentry) is enough; no need for a full metrics stack unless usage grows materially.
- **Rate limiting:** per-user token bucket in Redis on message send and on auth endpoints, to prevent abuse — required even at small scale since it's cheap to add and expensive to retrofit.

---

## Conventions

- **Python:** PEP8 via `ruff`, type hints everywhere, async/await for all I/O-bound code, no bare `except:`
- **React:** functional components only, one component per file, colocate styles with Tailwind classes, no inline business logic in JSX — extract to hooks/services
- **API:** REST for CRUD (users, channels, message history), WebSocket only for real-time delivery (new message, typing indicator, presence)
- **Naming:** snake_case (Python), camelCase (TypeScript/React), kebab-case (routes/files)
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`)
- **Branching:** `main` protected, feature branches `feature/<short-desc>`, PR required (even solo — good habit)

---

## SECURITY REQUIREMENTS (chat-specific)

- Passwords hashed with bcrypt/argon2, never logged or returned in API responses.
- JWT secret loaded from environment variable via `pydantic-settings`, never committed.
- WebSocket connections must authenticate via token **before** being allowed to join a channel — validate on every connection, not just on initial page load.
- Server must validate channel membership on every message read/write — never trust a client-supplied `channel_id` alone.
- CORS restricted to known frontend origin(s); no wildcard origins in production.
- All traffic over TLS in production (terminate at load balancer/platform level).

---

## REPOSITORY STRUCTURE

```
chatspace/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/            # REST routes
│   │   ├── ws/               # WebSocket connection manager & handlers
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # business logic
│   │   ├── db/                # session, migrations
│   │   └── core/              # config, security, deps
│   ├── tests/
│   ├── alembic/
│   └── pyproject.toml        # uv-managed
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── api/
│   │   └── store/
│   └── tests/
├── docker-compose.yml
├── .claude/
├── knowledge/
├── architecture/              # ADRs live here
└── docs/
```

---

## OPEN DECISIONS (resolve via ADR before building the relevant feature)

- [ ] DM data model: reuse `channels` table (2-member private channel) vs a dedicated `direct_messages` table
- [ ] Pagination strategy for message history (cursor-based recommended over offset)
- [ ] Deployment target: single Docker host vs Render/Fly.io/Railway
- [ ] File/image attachment storage (S3-compatible bucket) — in scope for v1 or deferred?