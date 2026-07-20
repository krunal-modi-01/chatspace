# chatspace Accessibility Guidelines

> Owner: `accessibility-auditor` + `frontend-engineer`. Status: **Proposed** (human design gate). Part of the design documentation set ([ADR-0013](../../architecture/adr/0013-design-documentation-structure.md)). Cross-cutting: referenced by [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md), [`INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md), and [`UX_GUIDELINES.md`](UX_GUIDELINES.md); consolidates the a11y requirements previously scattered across functional-spec §9 and tasks T36/T47/T52.

---

## 1. Standard & scope

- **Official standard: WCAG 2.2 AA** — adopted 2026-07-20; the accessibility target for all chatspace v1 screens, referenced consistently by the functional spec (§9), PRD §11, and the accessibility tasks (T36/T47/T52/T80/T81). It supersedes the earlier 2.1 AA baseline — 2.2 AA is a superset, so meeting it satisfies 2.1 AA.
- **What 2.2 adds over 2.1** (the deltas to design in; the remainder of 2.2 AA is identical to 2.1 AA):
  - **2.5.8 Target Size (Minimum)** — interactive targets ≥ **24×24 px** (our density tokens exceed this for default controls; the risk area is table-row icon actions — size them accordingly).
  - **2.4.11 Focus Not Obscured (Minimum)** — a focused element is never fully hidden behind the sticky header, pinned composer, drawer scrim, or toasts. Account for this in the z-index/layout (tokens §8).
  - **3.3.7 Redundant Entry / 3.3.8 Accessible Authentication (Minimum)** — already satisfied by our flows (no re-entry, standard password fields, no cognitive-function test).
- **Scope:** all authenticated and public screens, responsive web (native mobile is a non-goal). Both light and dark themes must pass independently.

---

## 2. Existing strengths to preserve (do not regress in the redesign)

The current codebase is already above average here. The redesign must **carry these forward**, not lose them while restructuring:
- **Live regions on the timeline** — `role="log"` + polite `aria-live` for incoming messages; typing indicator as a polite `status`.
- **Focus restoration after row mutations** — `InvitesPage`/`UsersPage` return focus to a sensible element when a row's action button is swapped or a row is removed (prevents focus falling to `<body>`).
- **`aria-describedby` wiring** in `FormField` (hint/error), `aria-invalid` on errored inputs, `role="alert"` on inline errors.
- **Real progress semantics** — the upload progress bar uses `role="progressbar"` with min/now/max.
- **Presence honesty** — "no presence observed yet" renders nothing rather than a false "Offline".

These become **acceptance criteria** for the corresponding redesigned components, not optional.

---

## 3. Requirements by area

### 3.1 Keyboard operability
- Every interactive element is reachable and operable by keyboard in a logical order; no keyboard traps (except intentional, escapable focus traps in Dialog/Drawer).
- **Menus** (`UserMenu`, any `role="menu"`): implement the WAI-ARIA menu pattern — arrow-key navigation, focus moves into the menu on open, `Escape` closes and returns focus to the trigger. *If the full pattern isn't implemented, use a plain disclosure (`aria-expanded` button + list of links), not `role="menu"`.* (The current `UserMenu` claims `role="menu"` without arrow-key support — fix one way or the other.)
- **Dialog / Drawer:** focus moves in on open, is trapped while open, `Escape` closes, focus returns to the opener.
- **⌘K quick switcher:** fully keyboard-driven (type, arrow, Enter, Escape).
- **Composer:** Enter sends, Shift+Enter newlines; the attach control is keyboard-focusable (not a label-only affordance).

### 3.2 Focus management
- **Visible focus** on every focusable element via the design-tokens §12 focus-ring recipe, in both themes; never remove an outline without replacing it; `:focus-visible`, not bare `:focus`.
- **Route changes** move focus to the new screen's heading (or main region) so screen-reader users are oriented.
- **Live updates** never steal focus (announce via live region only).
- **Membership removal while viewing** a channel moves focus to the "you were removed" notice / route-back control (F75).

### 3.3 Live regions & announcements
- Incoming messages, edits, deletes → polite announcements (existing `role="log"`), without focus theft.
- Typing → polite `status`, auto-clearing.
- **Channel add/remove** in the sidebar → polite announcement of channels appearing/disappearing (extends the existing live-region inventory, T52).
- **Toasts** → live-region backed (`status` for success/info, `alert` for error).
- Avoid announcement floods: batch/debounce where a burst would overwhelm (e.g. reconnect catch-up).

### 3.4 Semantics & ARIA
- **Landmarks:** the shell uses `<nav>` (sidebar, labeled), `<main>` (content), header/top-bar as appropriate; one `<h1>`-level heading per screen with a correct heading order.
- **Lists/tables:** the sidebar is a labeled navigation list; data tables use real table semantics with `<th scope>` and a caption (already done on existing tables — keep).
- **Icon-only controls** (`IconButton`) always carry an `aria-label`; decorative icons are `aria-hidden`.
- **Badges** are text labels, not status conveyed by color alone (see 3.6).
- **Forms:** label every control; associate hint/error via `aria-describedby`; set `aria-invalid` on error; announce errors with `role="alert"`.

### 3.5 Contrast
- Text meets 4.5:1 (normal) / 3:1 (large); UI component boundaries and focus indicators meet 3:1. Verify the token palette in **both** themes — especially `--color-text-tertiary` on raised/overlay surfaces, and the §12 badge tints (tinted background + same-hue text must still clear 4.5:1 for the text).
- The focus ring meets 3:1 against adjacent colors in both themes.

### 3.6 Color independence
- State is never conveyed by color alone: presence uses a dot **plus** a label/`aria-label` (online/last-seen), not just green/grey; badges carry text, not just a hue; validation pairs color with an icon/text and `aria-invalid`; the "(edited)"/deleted states are textual.

### 3.7 Motion
- Honor `prefers-reduced-motion: reduce` (tokens §11): disable transforms, slides, and skeleton shimmer; keep instantaneous opacity/color feedback (WCAG 2.3.3). No content flashes more than 3×/sec.

### 3.8 Media & images
- Avatars carry an accessible name (user's name); the initials fallback has `role="img"` + `aria-label` (existing — keep).
- Inline images use the filename (or better) as `alt`; video includes a `<track>` for captions (existing) and native controls.
- Download affordances name the file and size in the accessible label (existing — keep).

---

## 4. Per-component checklist (redesign)

| Component | Must satisfy |
|---|---|
| `Button` / `IconButton` | focus-visible ring; `disabled` not focusable-as-active; icon-only → `aria-label`; loading announced via `aria-busy` |
| `Badge` | text label present; contrast in both themes; not the sole carrier of state |
| `Input`/`FormField`/`Textarea`/`Select` | label; `aria-describedby` hint/error; `aria-invalid`; visible focus |
| `Menu` (UserMenu) | full menu keyboard pattern **or** downgrade to disclosure |
| `Dialog`/`Confirm` | focus-in, trap, Escape, return focus; labelled by its heading |
| `Drawer` (Channel details) | same as Dialog; not obscuring focused content behind scrim (2.4.11) |
| `Toast` | live-region; dismissible by keyboard; does not obscure focus |
| Table / list | `<th scope>`, caption; row actions keyboard-reachable; ≥24px targets |
| Timeline (grouped) | preserve `role="log"`/live region; hover-revealed actions also keyboard-reachable (focus-within); date separators not misread as messages |
| Composer | labelled textarea; keyboard-focusable attach; counter change not spammed to SR |
| `Skeleton` | `aria-busy`/hidden from SR as decorative while a `status` announces loading |
| `EmptyState` | heading + actionable link; not an error role |

---

## 5. Testing

- **Automated:** axe (or equivalent) on every screen, **light and dark**, target **0 serious/critical**. Wire into the frontend test/CI where feasible.
- **Keyboard walkthrough:** every primary flow (auth, browse/join, open+send in a channel, start+send a DM, add a member via picker, admin deactivate-with-confirm, theme toggle) completed mouse-free.
- **Screen-reader spot checks:** live-message announcement, typing, channel add/remove, "you were removed", form errors, dialog focus trap + return.
- **Contrast:** token palette audited in both themes (§3.5), including badge tints and the focus ring.
- **Reduced motion:** verify shimmer/slides/transforms are suppressed under the OS setting.

---

## 6. Relationship to the task plan

- The existing a11y passes (**T36** app, **T47** admin, **T52** my-channels) established the live-region/focus/contrast inventory. The redesign **extends** that inventory to every new component and to the restructured surfaces (shell, conversation surface, drawer, toast, ⌘K) via the M10 accessibility tasks — it does not start over.
- Any new interactive primitive ships with its §4 checklist satisfied as an acceptance criterion; a11y is not a separate later phase for new components, only a *hardening* pass for the assembled screens.
