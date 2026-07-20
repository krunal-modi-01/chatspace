# ADR-0017: Direct-message frontend surface & sidebar placement

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-20
- **Deciders:** product-manager + architect + human design gate
- **Tags:** frontend, ux, information-architecture, product

## Context
1:1 direct messages are v1 product scope: PRD R12/R13, functional-spec F46–F48, and the API contract all specify DM send/history, and ADR-0002 already fixed the DM data model (a `Message` with `recipient_id` set, no channel row). The **backend** DM work is task T22.

But there is **no frontend DM surface anywhere in the plan.** Milestone M5 (T30–T36) built auth, channels, messaging, presence/typing, and media UI — never DMs. So v1 as scoped can *store and serve* DMs over REST/WS but gives the user no way to *see or start* one. The 2026-07-20 review also asked, explicitly, whether DMs are near-term (so the app-shell IA must reserve a home for them) or deferred (so it should not).

The forcing question: **where do DMs live in the navigation, how does a user start and read one, and do we build the surface now or defer it?**

## Decision
We will build DMs on the **shared conversation surface** (ADR-0015) and give them a **dedicated sidebar section**, and we will build the surface as part of the redesign rather than deferring it — because the backend already exists and the conversation surface is being built anyway.

1. **Navigation home:** a **"Direct messages"** section in the persistent sidebar (ADR-0014), below Channels, listing recent 1:1 conversations with the peer's avatar, name, and presence dot. A **"New message"** affordance opens the user picker (ADR-0016) to start a conversation.
2. **Reading/sending:** a DM opens the **same conversation surface** channels use (ADR-0015), parameterized by `ConversationTarget = { kind: "dm", user_id }` — the messaging hooks are already generic over this, so the timeline, composer, optimistic send, edit/delete, typing, and presence come for free.
3. **No group DMs, no DM blocking** — unchanged from PRD non-goals; v1 DMs stay strictly 1:1.
4. **Timing:** the DM surface ships in the redesign milestone (M10), reusing the conversation surface from ADR-0015 rather than as a separate build. Until its rows exist, the sidebar section renders an empty state ("No direct messages yet — start one").

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — dedicated "Direct messages" sidebar section + shared conversation surface, built now | Matches the mental model users bring from Slack/Linear/Teams; clear separation of "rooms" (channels) vs "people" (DMs); reuses ADR-0015 surface and ADR-0016 picker; closes the scoped-but-unbuilt gap | One more sidebar section and a DM list/picker to build |
| B — unified "Conversations" list (channels + DMs intermixed) | One list, less chrome | Blurs the rooms-vs-people model team-chat users expect; makes "which channels am I in" harder to scan; diverges from R56's channel-list framing |
| C — DMs behind a separate route/page (not in the sidebar) | Keeps the sidebar smaller | Hides a primary communication mode behind a click; inconsistent with channels being always-visible; poor discoverability |
| D — defer DMs entirely to a later version | Less work now | Contradicts v1 scope (R12/R13, working backend); would force an app-shell IA redesign later to insert the section — the exact rework this effort avoids |

## Consequences
- **Positive:** DMs become a real, discoverable v1 surface built on infrastructure that already exists, at low marginal cost (surface + picker are shared). The IA reserves the section once, so no later nav redesign. Rooms-vs-people mental model stays crisp.
- **Negative / trade-offs:** Adds DM-specific frontend tasks the original plan omitted (a genuine scope correction, flagged in the consistency review). The sidebar carries a section that is empty until a user has DMs.
- **Follow-ups:** Task-breakdown M10 adds a DM list + "new message" picker + DM route reusing the conversation surface; PRD §11 records the sidebar placement; IA doc details the section. Depends on ADR-0014 (shell), ADR-0015 (surface), ADR-0016 (picker), ADR-0002 (data model, unchanged).

## Compliance / reversibility
Front-end only — the DM data model (ADR-0002) and API/WS contract are unchanged; this consumes existing endpoints. Reversible (hide the sidebar section) without any contract change. No regulatory implication.
