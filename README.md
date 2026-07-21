# chatspace

Team-chat / real-time messaging (Slack-style). FastAPI + PostgreSQL + Redis
backend, React + TypeScript (Vite) frontend.

- **Backend:** `backend/` — FastAPI modular monolith, served under `/v1`.
- **Frontend:** `frontend/` — React 19 SPA (Vite). See [`frontend/README.md`](frontend/README.md).
- **Design/spec docs:** `docs/`. Architecture decisions: `architecture/`.

Operating conventions live in [`CLAUDE.md`](CLAUDE.md).

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager) — backend
- [Node.js](https://nodejs.org/) 20+ and npm — frontend

---

## Quick start (everything in Docker)

Brings up backend, frontend, and all backing services (Postgres, Redis,
MinIO, Mailpit) in one shot:

```bash
docker compose up --build
```

- Backend API: <http://localhost:8000/v1>
- Frontend: <http://localhost:5173>

---

## Local development

Run the app processes on your host (for hot-reload) while the backing
services run in Docker.

### 1. Start the backing services

```bash
docker compose up -d postgres redis minio minio-init mailpit
```

### 2. Backend

```bash
cd backend
uv sync                              # install dependencies
cp env.example .env                  # then fill in the placeholders
uv run alembic upgrade head          # run database migrations
uv run uvicorn app.main:app --reload --port 8000
```

The API is served under `/v1` (e.g. <http://localhost:8000/v1>).

> **Note:** Settings fail-fast on startup — there are **no** hardcoded
> fallbacks. You must set every value in `.env`, including a real
> `JWT_SIGNING_KEY` and a `BOOTSTRAP_ADMIN_PASSWORD` that satisfies the
> password policy (≥6 chars, at least one letter and one digit), or the
> app refuses to boot (ADR-0009). The default `DATABASE_URL` / `REDIS_URL`
> in `env.example` already match the docker compose services.
>
> To enable the optional Sentry-class error monitor, install the extra:
> `uv sync --extra observability` (off by default).

### 3. Frontend

```bash
cd frontend
npm install
cp env.example .env.local            # VITE_API_BASE_URL defaults to http://localhost:8000/v1
npm run dev
```

Dev server runs at <http://localhost:5173> (the origin the backend's CORS
config allows by default). See [`frontend/README.md`](frontend/README.md)
for the full script list and project structure.

---

## Common commands

| Task | Command |
|------|---------|
| Backend tests | `cd backend && uv run pytest` |
| Frontend tests | `cd frontend && npm run test` |
| Backend lint | `cd backend && uv run ruff check .` |
| Backend format | `cd backend && uv run ruff format .` |
| Backend typecheck | `cd backend && uv run mypy app` |
| Frontend lint | `cd frontend && npm run lint` |
| Frontend typecheck | `cd frontend && npm run typecheck` |
| Frontend build | `cd frontend && npm run build` |
| New migration | `cd backend && uv run alembic revision --autogenerate -m "message"` |
| Apply migrations | `cd backend && uv run alembic upgrade head` |
