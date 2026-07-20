# ADR-0014: App-shell navigation & information-architecture model

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-20
- **Deciders:** product-manager + architect + human design gate
- **Tags:** frontend, information-architecture, navigation, ux

## Context
The primary logged-in navigation surface was never owned by any document. Task T50 explicitly states the placement "decision [is] owned here (the current shell is top-bar nav with no sidebar)" — i.e. an implementation task was left to invent the app's information architecture. The result, confirmed in the 2026-07-20 review:

- The top navigation contains **one** item ("Browse channels"); the brand mark is not a link, so the Dashboard route (`/`) is unreachable after the first navigation.
- `/admin/users` — a PRD-mandated screen (R55/F72) — has **zero inbound links**; it is reachable only by typing the URL.
- The "My Channels" list (R56, the PRD's stated *primary* navigation surface) renders as a sidebar that, on mobile, **stacks above the page content**, so every screen opens below the full channel list.
- Direct messages (R12/R13) are v1 scope but have **no navigation home** at all, and no frontend surface was ever scoped (see ADR-0017).

The forcing question: **what is the app-shell navigation model — the persistent structure every authenticated screen renders inside?** PRD R56 requires "My channels" to be the primary navigation surface; R58 (added in PRD v4) requires every role-appropriate destination to be reachable by click with no orphan routes; the product must work on mobile browsers (PRD §11, mobile is responsive-web, not native).

## Decision
We will adopt a **persistent left sidebar as the primary navigation surface, with a contextual top bar and a single content region**, collapsing to a drawer on small viewports.

1. **Sidebar (persistent, `≥ md`)**, top to bottom:
   - **Workspace identity** — the chatspace mark, which links to the app home.
   - **Global search / command entry** (⌘K) — opens the quick switcher (channels now; DMs and users as those surfaces land).
   - **Channels** — the "My Channels" list (R56/F73), live-updated (R57/F74/F75). A "Browse / create" affordance heads the section.
   - **Direct messages** — recent 1:1 conversations (ADR-0017), with a "New message" affordance that opens the user picker (ADR-0016). The section is present in the shell from the start even before per-conversation rows exist.
   - **Footer cluster** — Settings, an **Admin** entry visible only to System Admins (linking a grouped Invite Management + User Management area, fixing the orphaned `/admin/users`), and the account menu + theme toggle.
2. **Top bar (contextual)** — carries the current surface's title and its primary actions (e.g. a channel's name, member count, and a "Details" button). It is not a second navigation menu.
3. **Content region** — the active surface (a conversation, a settings screen, an admin screen) owns the remaining space.
4. **Small viewports (`< md`)** — the sidebar collapses into a **drawer** toggled by a menu button in the top bar; content is never pushed below the navigation.
5. Every role-appropriate destination is reachable from the sidebar (R58). The Dashboard route is resolved by ADR/IA (redirect `/` to the last-visited or first channel rather than a dead landing page).

This supersedes the implicit top-bar-only shell and formally closes the T50 unowned decision.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — persistent left sidebar + contextual top bar + mobile drawer | Matches R56 ("My channels" primary surface) and the mental model users bring from Slack/Linear/Teams; gives DMs and Admin real homes; single, well-understood responsive pattern | Requires rebuilding the app shell (T66–T68); more layout to maintain than a top bar |
| B — top-bar nav only (current) | Simplest; already built | Cannot hold Channels + DMs + Admin + account without crowding; produced the orphaned/unreachable routes and the mobile stacking bug the review found |
| C — dual top bar + sidebar | Familiar from some dashboards | Two nav systems compete for the same jobs; ambiguity about where a destination lives; more chrome, less content |
| D — drawer-only (hidden by default on all sizes) | Maximal content space | Hides the primary navigation surface R56 wants *always visible* on desktop; adds a click to every navigation |

## Consequences
- **Positive:** The navigation graph becomes complete and legible — no orphan routes, admin reachable, DMs homed, current location always clear. Mobile gets a real pattern instead of a stacked list. The IA is now specified in `docs/design/INFORMATION_ARCHITECTURE.md` and testable via R58.
- **Negative / trade-offs:** The app shell is rebuilt (blast radius across every authenticated screen), and the sidebar reserves space for DMs before the DM surface fully ships. Mitigated by sequencing (tokens → primitives → shell) and by the DM section degrading to an empty state until ADR-0017 lands.
- **Follow-ups:** Realized by task-breakdown M10 (T66 shell, T67 nav-graph repair, T68 mobile drawer, T69 quick switcher). IA documented in `INFORMATION_ARCHITECTURE.md`; PRD R58 makes it a requirement.

## Compliance / reversibility
Front-end structural only — no backend, API, or schema impact. Reversible (the shell is a component boundary). No regulatory implication. Depends on ADR-0016 (user picker) and pairs with ADR-0015 (conversation surface) and ADR-0017 (DM surface).
