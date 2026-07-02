# ADR-0008: Deployment target — managed PaaS (recommend Render)

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed (direction human-confirmed: managed PaaS; specific provider awaits human sign-off)
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** deployment, infrastructure, cost

## Context
chatspace must run 1–2 FastAPI instances behind a load balancer, a single managed Postgres (daily backups), and a single Redis, serving ~1,000 concurrent users with WebSockets and TLS in production (R21/R23/F67). The constitution forbids Kubernetes/AWS/Terraform and asks for "a single Docker host / small managed platform (Render, Fly.io, Railway — TBD via ADR)." The human confirmed the direction is a **managed PaaS**; this ADR recommends one and stays **Proposed** for human sign-off. Key needs: first-class **WebSocket / long-lived connection** support, **managed Postgres with automated daily backups**, a **managed Redis**, private networking between app and datastores, simple env-var secret management, and auto TLS. Object storage is separate (ADR-0007), since PaaS options generally lack a built-in S3.

The forcing question: which managed PaaS best fits a self-hostable, small-team, 1,000-user chat product without k8s?

## Decision
We will deploy to **Render** as the recommended managed PaaS, pending human sign-off at the 🔒 gate:

- **App:** 1–2 Render Web Services running the FastAPI container (`docker-compose` parity locally), health-checked, behind Render's managed load balancer with **native WebSocket support** and **auto-managed TLS**.
- **Postgres:** Render Managed PostgreSQL with **automated daily backups** (RPO up to 24 h, accepted risk) and point-in-time recovery available on higher tiers; a **restore drill is required before GA**.
- **Redis:** Render Key Value (managed Redis) for pub/sub fan-out, presence, and rate limiting — single instance, no cluster (single-Redis SPOF accepted).
- **Networking/secrets:** private networking between app and datastores; secrets as Render environment variables via `pydantic-settings` (JWT key, DB URL, Redis URL, SMTP creds, S3 creds), never committed (R2/R24).
- **Object store:** provisioned separately (ADR-0007) — e.g. Cloudflare R2 or DO Spaces — chosen at deploy time.
- **Email:** external SMTP/transactional provider (ADR-0010), a hard first-run prerequisite.

Render is recommended over Fly.io and Railway for this workload because it offers the best balance of first-class managed Postgres **with automated backups**, a managed Redis, native WebSocket support, private networking, and low operational overhead for a small team — without k8s. Fly.io and Railway are viable and are recorded as alternatives.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — Render | Managed Postgres with automated daily backups + PITR on paid tiers; managed Redis (Key Value); native WebSocket support; private networking; auto TLS; simple env-var secrets; strong DX for a small team | No built-in object store (media provider is separate — expected per ADR-0007); egress/instance costs to monitor as video usage grows |
| B — Fly.io | Excellent for long-lived WebSocket connections and running close to the metal; global regions | Managed Postgres offering is newer/less turnkey for backups; Redis typically via a third party (Upstash); more ops knobs than a small team needs at 1,000 users |
| C — Railway | Very simple DX; Postgres + Redis plugins; WS support | Historically less mature managed-backup/DR story; smaller operational track record for the reliability target (99.5%) |
| D — Single Docker host (VPS) | Cheapest; full control; matches self-host ethos most literally | Operator owns backups, TLS, monitoring, patching, and LB by hand — more ops burden and higher DR risk than a managed platform for the same 99.5% target |

## Consequences
- **Positive:** Managed Postgres backups, managed Redis, LB, and TLS come out of the box, freeing the small team from undifferentiated ops and directly supporting the 99.5% uptime and daily-backup targets. WebSocket support is native, so ADR-0001's combined REST+WS instances deploy without special handling. Env-var secrets align with the constitution.
- **Negative / trade-offs:** Media object storage and transactional email are separate providers (multi-vendor surface). Platform lock-in is modest but real (service definitions, private networking) — mitigated by the container being portable. Single Redis remains a SPOF (accepted). Video egress cost must be monitored (§9 risk).
- **Follow-ups:** `devops-engineer` / `infrastructure-engineer` produce the Render service definitions, wire private networking and env secrets, configure health checks, and **execute a Postgres restore drill before GA**; the object-store provider (ADR-0007) and SMTP provider (ADR-0010) are chosen alongside this at deploy time. Human confirms the specific PaaS at the 🔒 gate.

## Compliance / reversibility
Moderately reversible: the app is a portable container and datastores are standard Postgres/Redis, so migrating to Fly.io, Railway, or a VPS later is a re-provisioning + data-migration exercise, not a rewrite. This ADR remains **Proposed** specifically so the human owns the provider decision. TLS-in-production (R23/F67) is satisfied by the platform's managed certificates. No regulatory implication at v1 scope.
