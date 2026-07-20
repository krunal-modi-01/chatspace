# chatspace Information Architecture

> Owner: `architect` (design) + `product-manager`. Status: **Proposed** (human design gate). Part of the design documentation set ([ADR-0013](../../architecture/adr/0013-design-documentation-structure.md)). Realizes [ADR-0014](../../architecture/adr/0014-app-shell-navigation-model.md) (shell/nav), [ADR-0015](../../architecture/adr/0015-conversation-surface-model.md) (conversation surface), [ADR-0017](../../architecture/adr/0017-direct-message-surface.md) (DM placement). Makes PRD **R58** (navigation) testable.
>
> Defines *composition* — how screens are organized into a navigable whole. Values come from [`design-tokens.md`](../../architecture/design-tokens.md); components from [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md); behavior/principles from [`UX_GUIDELINES.md`](UX_GUIDELINES.md).

---

## 1. IA principles

1. **The conversation is the destination.** Navigation exists to get the user into a conversation fast and then disappear. Chrome is minimal; the active surface dominates (ADR-0015).
2. **Location is always unambiguous.** Every screen announces what it is (title) and where it sits (active nav state). A user dropped onto any screen knows where they are.
3. **Reachable by click, not just by URL (R58).** Every role-appropriate destination has a path through the sidebar. No orphan routes. This is a requirement, not a convention — it is why `/admin/users` (unreachable today) and the Dashboard (orphaned today) are defects.
4. **Rooms vs people.** Channels ("rooms") and DMs ("people") are distinct sections with distinct mental models (ADR-0017); they are not merged into one list.
5. **Role-gated, not role-hidden-only.** System-Admin destinations appear *in the nav* for System Admins and are absent (not just route-guarded) for everyone else.

---

## 2. Navigation model (the app shell)

Authenticated screens render inside a persistent shell (ADR-0014):

```
┌───────────────┬─────────────────────────────────────────────┐
│  SIDEBAR      │  TOP BAR (contextual: title + primary actions)│
│  (persistent  ├─────────────────────────────────────────────┤
│   ≥ md)       │                                             │
│               │  CONTENT REGION                              │
│  • workspace  │  (the active surface — conversation,         │
│  • search ⌘K  │   list screen, admin screen, settings)       │
│  • Channels   │                                             │
│  • Direct msgs│                                             │
│  • ─────────  │                                             │
│  • Settings   │                                             │
│  • Admin*     │                                             │
│  • Account+   │                                             │
│    theme      │                                             │
└───────────────┴─────────────────────────────────────────────┘
        *Admin visible only to System Admins
```

- **Sidebar** is the primary navigation surface (satisfies R56 "My channels" as primary). Rows follow the DESIGN_SYSTEM §4.2 nav-row spec (single line, glyph + name + optional signal).
- **Top bar** is *contextual*, not a second menu: it carries the current surface's title and primary actions (e.g. a channel's name + member/presence summary + **Details**; a list screen's create action). On `< md` it also hosts the **drawer toggle** (menu button) and the workspace mark.
- **Content region** is the active surface.
- **`< md`:** the sidebar collapses into a **drawer** over the content; content never stacks below navigation (fixes the current mobile stacking bug).

---

## 3. Sitemap & route map

| Route | Screen | Nav home | Auth | Notes / change |
|---|---|---|---|---|
| `/login` | Login | (public) | Unauth | Aurora surface |
| `/register?token=` | Invite registration | (public, from email) | Invited | Email locked (F4) |
| `/password-reset` | Reset request | link from Login | Unauth | Uniform response (F15) |
| `/password-reset/confirm?token=` | Reset confirm | (from email) | Unauth | Stale-token state (F17) |
| `/` | **Home** | workspace mark | Auth | **Resolved:** redirect to the last-visited channel, else the first "My channel", else an onboarding empty state. No dead landing page. |
| `/channels` | Browse & create | Channels section header ("Browse / Create") | Auth | Browse-first; create behind a disclosure (not the dominant card) |
| `/channels/:id` | **Channel conversation** | Channels list row | Member | Conversation surface (ADR-0015); members/admin in the **Details drawer**, not the page |
| `/dms/:userId` | **DM conversation** *(new)* | Direct messages list row / "New message" | Participant | Same conversation surface (ADR-0015/0017); reuses `ConversationTarget={kind:"dm"}` |
| `/settings/password` | Change password | Settings (footer) | Auth | — |
| `/settings/sessions` | Active sessions | Settings (footer) | Auth | — |
| `/settings/profile` | Profile *(new/expanded)* | Settings (footer) | Auth | Home for name/avatar edit + avatar **upload** (resolves API open-Q#1; retires the raw "Avatar URL" field) |
| `/admin/invites` | Invite management | **Admin** (footer, role-gated) | System Admin | — |
| `/admin/users` | User management | **Admin** (footer, role-gated) | System Admin | **Fixed:** was reachable only by URL; now linked from the Admin area |
| `/404` | Not found | — | any | Re-skinned on tokens, rendered in-shell when authed |

**Admin grouping:** `/admin/invites` and `/admin/users` sit under one **Admin** section (a small landing or a two-item group) so both are reachable and cross-linked — the current build links only invites and never users.

---

## 4. Sidebar structure (detail)

Top to bottom:

1. **Workspace identity** — the chatspace mark. Links to `/` (home). *(Today it is an inert `<span>`; making it a link restores access to home.)*
2. **Search / ⌘K** — opens the quick switcher (channels now; DMs and users as those surfaces mature). Keyboard-first entry point (UX_GUIDELINES).
3. **Channels** — section header with a **Browse / Create** affordance (→ `/channels`), then the live "My Channels" list (R56/F73, live per R57/F74/F75). Rows: `#`/lock glyph · name (truncates) · unread signal (future). Empty → `EmptyState` ("You haven't joined any channels yet" → Browse). Role is **not** shown in the nav row (it belongs in the channel, not the list).
4. **Direct messages** (ADR-0017) — section header with **New message** (→ user picker, ADR-0016), then recent 1:1 conversations: peer `Avatar` + presence dot · name. Empty → `EmptyState` ("No direct messages yet — start one"). Present in the shell from the start even before rows exist.
5. **Divider.**
6. **Footer cluster** — **Settings** (→ profile/password/sessions), **Admin** (role-gated, → invites/users), and the **account menu + theme toggle** (avatar via `Avatar`, not a bare initial).

---

## 5. Screen inventory & information hierarchy

For each screen: **primary** (dominates, first read) → **secondary** → **tertiary**. This is the antidote to the review's "everything appears equally important."

- **Login / Register / Reset** — *Primary:* the form + its one heading. *Secondary:* the alternate-path link (register/sign-in/forgot). *Tertiary:* ambient identity. Register adds a show-password toggle and inline password-rule validation.
- **Home (`/`)** — resolves to a conversation (§3); not a screen with its own hierarchy.
- **Browse & create channels** — *Primary:* the browse list + join. *Secondary:* create (behind a disclosure/button — it is the rarer action, so it is not the dominant top card as it is today). *Tertiary:* pagination, counts. Empty browse → `EmptyState` cross-linking create.
- **Channel conversation** — *Primary:* the message timeline + composer (full height, ADR-0015). *Secondary:* the header (name, member/presence summary, Details). *Tertiary (on demand):* the Channel details drawer (members, roles, add-member, leave, frozen/zero-admin state). At most **one** contextual banner at a time (removal, leave-warning, frozen) — never the current stack of four.
- **DM conversation** — same hierarchy as a channel, minus members/roles; the Details drawer (if any) shows the peer's profile summary.
- **Settings — profile / password / sessions** — *Primary:* the single task's form/list. *Secondary:* status/confirmation. Sessions: current-device badge + per-row revoke; relative "last active" times.
- **Admin — invites** — *Primary:* the invite list (status, expiry-relative). *Secondary:* issue form. *Tertiary:* status filter. Errors (409 already-registered, 502 undeliverable) inline.
- **Admin — users** — *Primary:* the searchable user list. *Secondary:* search (debounced, with a result count). *Tertiary:* per-row deactivate/reactivate (deactivate via `Dialog` confirm — it drops sessions immediately). Last-active-admin 409 inline.
- **Quick switcher (⌘K)** — *Primary:* the query + results (channels; later DMs/users). Keyboard-navigable list.
- **Not found** — *Primary:* the message + a route home. On-system, in-shell when authed.

---

## 6. Navigation flows & click budgets (R58)

Common tasks, measured from anywhere in the app:

| Task | Path | Budget |
|---|---|---|
| Open a channel I'm in | sidebar Channels → row | 1 click |
| Read/send in it | (already the primary surface) | 0 extra |
| See who's in a channel | header → Details | 1 click |
| Add someone to a private channel | Details → Add member → search name → add | search, not a UUID (ADR-0016) |
| Start a DM | sidebar DMs → New message → search → send | via picker (ADR-0016/0017) |
| Browse/join a public channel | sidebar Channels → Browse → Join | 2 clicks |
| Reach admin (System Admin) | sidebar → Admin → Invites/Users | 2 clicks; both reachable |
| Change password / see sessions | sidebar → Settings → … | 2 clicks |

No role-appropriate destination exceeds 2 clicks; none requires typing a URL.

---

## 7. Discoverability & wayfinding

- **Active state:** the current sidebar row and section are visibly active (selected state, DESIGN_SYSTEM §4.2). The top-bar title mirrors it.
- **Titles:** every screen has one `text-heading`/`text-display` that names it.
- **Empty states cross-link** to the action that resolves them (no dead ends).
- **No breadcrumbs in v1** — the hierarchy is shallow (shell → section → surface); breadcrumbs would be chrome without payoff. Revisit only if depth grows.
- **Naming consistency:** one label per concept — the sidebar section, the browse screen, and any nav entry for channels all read consistently (the review found "Channels"/"Channels"/"Browse channels" for two concepts).

---

## 8. Deferred / open

- **Unread indicators** per channel/DM row — designed-for in the nav-row spec (trailing signal) but data/semantics are a follow-up; not required for the redesign's structural phases.
- **Persistent details drawer at `≥ lg`** — optional enhancement (§6 responsive), not required for v1.
- **Group DMs, DM blocking** — out of scope (PRD non-goals), unaffected by this IA.
