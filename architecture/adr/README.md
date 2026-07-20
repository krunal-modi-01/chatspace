# Architecture Decision Records — chatspace

This directory holds the Architecture Decision Records (ADRs) for chatspace. Each ADR captures one significant, non-obvious decision: the context that forced it, the options weighed, the choice, and its consequences and reversibility. ADRs follow `templates/adr.md`.

All ADRs below are **Proposed** — the human owns the 🔒 Architecture gate and must sign them off before implementation begins. ADR-0008 (deployment target) and ADR-0007 (media storage) record human-confirmed *directions*; the specific provider choices remain with the human. Numbering is sequential with no gaps.

ADR-0013–0017 (dated 2026-07-20) record the **design/redesign** decisions that came out of the 2026-07-20 UX review: the design-documentation structure, the app-shell navigation model, the conversation-surface model, the workspace user directory, and the direct-message surface. These are owned jointly by `product-manager` + `architect` and gated by a human **design** sign-off (alongside the standard architecture gate where they touch the API surface, e.g. ADR-0016). They are supported by the design documentation under [`docs/design/`](../../docs/design/) and [`architecture/design-tokens.md`](../design-tokens.md).

The Technical Specification that these ADRs support: [`docs/spec/chatspace-v1-technical-spec.md`](../../docs/spec/chatspace-v1-technical-spec.md). Traces to the functional spec: [`docs/spec/chatspace-v1-functional-spec.md`](../../docs/spec/chatspace-v1-functional-spec.md).

| Number | Title | Status | Date |
|--------|-------|--------|------|
| [ADR-0001](0001-modular-monolith-fastapi.md) | Modular monolith FastAPI serving REST + WebSocket | Proposed | 2026-07-02 |
| [ADR-0002](0002-dm-data-model.md) | Direct-message data model (recipient_id on messages, no channel row) | Proposed | 2026-07-02 |
| [ADR-0003](0003-cursor-pagination.md) | Cursor (keyset) pagination for message history | Proposed | 2026-07-02 |
| [ADR-0004](0004-realtime-delivery-fanout.md) | Real-time delivery — Redis pub/sub, persist-then-publish, at-least-once + client dedup | Proposed | 2026-07-02 |
| [ADR-0005](0005-message-id-scheme.md) | Time-sortable message identifiers (UUIDv7) | Proposed | 2026-07-02 |
| [ADR-0006](0006-revocable-sessions.md) | Revocable sessions — server-side session store + Redis revocation check | Proposed | 2026-07-02 |
| [ADR-0007](0007-media-object-storage.md) | Media storage — S3-compatible abstraction, validate-through-app, separate-origin signed URLs | Proposed | 2026-07-02 |
| [ADR-0008](0008-deployment-target.md) | Deployment target — managed PaaS (recommend Render) | Proposed | 2026-07-02 |
| [ADR-0009](0009-system-admin-bootstrap.md) | System Admin bootstrap — env-seeded at startup | Proposed | 2026-07-02 |
| [ADR-0010](0010-transactional-email.md) | Transactional email — provider-agnostic SMTP abstraction, fail-loud, no queue | Proposed | 2026-07-02 |
| [ADR-0011](0011-forced-password-change-unblock.md) | Forced password-change unblock — reuse self-service reset (amends ADR-0009) | Proposed | 2026-07-08 |
| [ADR-0012](0012-per-user-websocket-topic.md) | Per-user WebSocket topic for membership lifecycle events (extends ADR-0004) | Proposed | 2026-07-13 |
| [ADR-0013](0013-design-documentation-structure.md) | Design documentation structure (tokens → design system → IA/UX → a11y) | Proposed | 2026-07-20 |
| [ADR-0014](0014-app-shell-navigation-model.md) | App-shell navigation & information-architecture model (persistent sidebar + drawer) | Proposed | 2026-07-20 |
| [ADR-0015](0015-conversation-surface-model.md) | Conversation surface model (full-height timeline + details drawer, flat grouped rows) | Proposed | 2026-07-20 |
| [ADR-0016](0016-workspace-user-directory.md) | Workspace user directory for member & DM selection (`GET /v1/users/search`) | Proposed | 2026-07-20 |
| [ADR-0017](0017-direct-message-surface.md) | Direct-message frontend surface & sidebar placement (reuses ADR-0015) | Proposed | 2026-07-20 |
