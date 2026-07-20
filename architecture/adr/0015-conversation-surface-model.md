# ADR-0015: Conversation surface model

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-20
- **Deciders:** product-manager + architect + human design gate
- **Tags:** frontend, ux, information-architecture

## Context
In the current `ChannelPage`, the message timeline is a fixed-height (`h-[32rem]`) card rendered **below** the channel header, up to four stacked banners, the members table, members pagination, and an "Add a member" form. In a team-chat product this inverts the point of the screen: the most frequent action (reading and sending messages) is the one the user must scroll to, while channel *administration* — a rare action — dominates the top of the page. The message rendering itself compounds this: each message is a bordered, rounded box; a user's own messages flip to right-alignment (a consumer-messenger pattern) while still showing avatar + name + timestamp (a workspace-timeline pattern); and Edit/Delete are permanently visible under every own message.

The forcing question: **how is a conversation laid out, and what is the message-rendering model?** This decision also gates DM reuse — the messaging hooks (`useMessageHistory`, `messagesApi`) are already written generically over a `ConversationTarget`, so channels and DMs should share one surface (see ADR-0017).

## Decision
We will make the **conversation the dominant, full-height surface**, and move channel administration into a drawer.

1. **Full-height layout:** header (conversation name, member/presence summary, and a **Details** action) at the top; a **flexing message timeline** that owns all remaining vertical space; a **composer pinned to the bottom** of the viewport. The composer is reachable without scrolling regardless of message or member count.
2. **Channel details drawer:** the member list, role management, add-member, leave, and the zero-admin/frozen affordances move into a right-side **"Channel details"** slide-over opened from the header. They are secondary to the conversation and appear on demand (progressive disclosure), not stacked above it.
3. **Flat, grouped timeline:** messages render as **flat, left-aligned rows** — no per-message border boxes, no alignment flipping. Consecutive messages from the same author within a short window are **grouped** under one avatar + name + timestamp; **date separators** divide days. Message actions (edit/delete for the author) appear on **hover/focus-within**, not as standing chrome. Deleted messages show the retained tombstone ("This message was deleted"); edited messages show an "(edited)" marker.
4. **One surface, reused:** channels and DMs render through the same conversation surface, parameterized by `ConversationTarget` (ADR-0017). Live events (`message.created/edited/deleted`, typing, presence) render in place per the existing WS contract.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — full-height timeline + details drawer + flat grouped rows | Conversation is primary; matches the density/scan model of Slack/Linear; drawer keeps admin available but out of the way; one surface reused by DMs | High blast radius (rebuilds `ChannelPage` + timeline); needs a drawer primitive and a feature flag for safe rollout |
| B — keep the stacked card | No rework | Leaves the core product task subordinate to administration; the defect the review ranked P0 |
| C — messenger bubbles (keep right-alignment) | Familiar from consumer chat | Wrong model for a work tool where a single scan column and author grouping read faster; caps density; conflicts with avatar+name+timestamp already shown |
| D — members as an in-page tab beside "Messages" | Keeps everything on one route | Still competes with the timeline for the viewport; a drawer overlays without stealing conversation height |

## Consequences
- **Positive:** The conversation dominates; the composer is always reachable; density and scanability rise; DMs get their surface for free (ADR-0017). Mobile improves substantially because the members table is no longer stacked above the chat.
- **Negative / trade-offs:** The largest single front-end change in the redesign; must ship behind a route-level feature flag with the old page retained until acceptance passes. Author grouping and date separators add rendering logic to the timeline.
- **Follow-ups:** Realized by M10 (T70 layout refactor, T71 timeline redesign, T72 composer refinement); DM reuse in the DM tasks. Requires the Drawer/Modal primitive from DESIGN_SYSTEM.md.

## Compliance / reversibility
Front-end only — no backend, API, or WS-contract change (it consumes the existing event envelope). Reversible behind the feature flag. No regulatory implication. Pairs with ADR-0014 (shell) and ADR-0017 (DM reuse).
