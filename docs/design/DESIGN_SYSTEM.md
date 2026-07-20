# chatspace Design System

> Owner: `frontend-engineer` + `architect` (design). Status: **Proposed** (human design gate). Part of the design documentation set defined by [ADR-0013](../../architecture/adr/0013-design-documentation-structure.md).
>
> **What this document is:** the definition of *components and layout* — the primitive inventory, each primitive's variants/props/states, the composite patterns built from them, the page-layout templates, and responsive behavior.
>
> **What it is not:** it defines **no raw values**. Every color, size, radius, duration, and z-index is a token from [`architecture/design-tokens.md`](../../architecture/design-tokens.md), referenced by name. A hardcoded hex/px/ms here is a defect (ADR-0013 §15). Accessibility requirements per component defer to [`ACCESSIBILITY_GUIDELINES.md`](ACCESSIBILITY_GUIDELINES.md); composition and behavior to [`INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md) and [`UX_GUIDELINES.md`](UX_GUIDELINES.md).

---

## 1. Principles of the component layer

1. **Reuse before build.** Check `frontend/src/components/ui/` first (design-tokens §14). A new screen composes primitives; it does not restyle from scratch.
2. **One implementation per concept.** There is exactly one `Badge`, one confirmation pattern, one table treatment. The review found six badge implementations and four confirmation dialects — that is the failure state this layer exists to prevent.
3. **States are complete by contract.** Every interactive primitive implements the state set in design-tokens §13 (`default`/`hover`/`focus-visible`/`disabled`/`loading` where applicable). "It usually looks fine" is not done.
4. **Tokens in, no values out.** Components read token names. If a needed value does not exist as a token, add the token first (design-tokens.md), then consume it.
5. **Accessible by construction.** Semantics, focus, and contrast are part of the component, not a later audit pass.

---

## 2. Primitive inventory (canonical)

| Primitive | Status | Variants / sizes | Notes |
|---|---|---|---|
| `Button` | **Revise** | `primary` · `secondary` · `danger` · `ghost` · `link`; sizes `sm`/`md`; `fullWidth`; `isLoading` | Intrinsic width by default (see §3.1) |
| `IconButton` | **New** | sizes `sm`/`md`; same variants as `Button` where relevant | Square, icon-only, needs `aria-label` |
| `Badge` | **New** | `neutral` · `accent` · `success` · `warning` · `danger` | Replaces all inline pills (design-tokens §12) |
| `Input` / `FormField` | Keep | — | `FormField` wires label + input + hint/error + `aria-describedby` |
| `Textarea` | **New** | — | Extract from composer + message-edit + add-member |
| `Select` | Keep | — | Matches `Input` treatment |
| `Card` | Keep | — | Elevation-2 surface (tokens §7); not the answer to everything (§4) |
| `AlertBanner` | **Revise** | `info` · `warning` · `error` · `success` | Colors from tokens §12, not raw palettes |
| `Toast` | **New** | `success` · `error` · `info` | Background outcomes; live-region backed |
| `Avatar` | **Revise** | sizes `sm`/`md`; optional presence dot | Adopt in the shell (`UserMenu` re-implements it today) |
| `Skeleton` | **New** | line / block / row | Reduced-motion aware (tokens §11) |
| `EmptyState` | **New** | — | Icon + one line + primary action |
| `Confirm` | **New** | inline · `Dialog` | Unifies leave/delete/deactivate/demote |
| `Drawer` | **New** | right slide-over | `--z-drawer`; used by the conversation Details panel |
| `Modal` / `Dialog` | **New** | centered | `--z-modal`; destructive+irreversible confirms |
| `AuroraBackground` | Keep | — | Auth/onboarding only (tokens §3) |
| `ThemeToggle` | Keep | — | Persists preference |

"Revise" = exists, changes are specified below. "New" = build in `ui/` before the screen that needs it.

---

## 3. Primitive specs

### 3.1 Button — *revise*
- **Width:** intrinsic (content-sized) **by default**; full width is opt-in via `fullWidth`. *(Today `w-full` is the base and 15+ call sites undo it with `w-auto`; invert this.)* Auth forms use `fullWidth`; everything else does not.
- **Sizes:** `md` (default, `--control-height-md`) for forms and page actions; `sm` (`--control-height-sm`) for controls inside table rows and dense toolbars. *(Adding `sm` removes the ~8 hand-rolled table buttons.)*
- **Variants:** `primary` (accent fill), `secondary` (bordered surface), `danger` (danger fill), **`ghost`** (no border/fill, hover surface — for low-emphasis/table actions), **`link`** (text + accent, for inline navigation-as-action and to replace the button-classes-copied-onto-`<Link>` in the Dashboard).
- **Link rendering:** support rendering as an anchor/`<Link>` (`asChild` or `as`) so a navigation action never means copy-pasting the class string.
- **States:** all of design-tokens §13; `isLoading` shows the spinner and swaps to `loadingText` — never a silent disabled no-op.

### 3.2 Badge — *new*
- One primitive replacing `RoleBadge` (defined twice), `VisibilityBadge`, `StatusBadge` (invites), the active/inactive pill, and the "This device" pill.
- Variants map to the design-tokens §12 tint recipe: `neutral`, `accent`, `success`, `warning`, `danger`.
- Mapping guide (semantics, not hardcoded): role `admin` → `accent`, `member` → `neutral`; visibility → a glyph in dense contexts (`#`/lock), a `neutral` badge only where a label is warranted; invite `pending` → `warning`, `accepted` → `success`, `revoked`/`expired` → `danger`/`neutral`; user active → `success`, inactive → `neutral`.
- Never carries interactive behavior; it is a label. Contrast requirements: ACCESSIBILITY_GUIDELINES §badges.

### 3.3 Inputs — `Input` / `FormField` / `Textarea` / `Select`
- `FormField` remains the standard (label + control + hint/error, `aria-describedby`, `aria-invalid`). Keep.
- **`Textarea` (new):** extract the styles currently duplicated in `MessageComposer`, the message-edit box, and any multi-line field into one primitive matching `Input`'s border/focus/disabled treatment.
- Show-password affordance: password inputs support a reveal toggle (see UX_GUIDELINES interaction patterns).
- Inline validation: where a rule is stated in a hint (e.g. password "letter + digit"), validate against it inline rather than only on submit.

### 3.4 Avatar — *revise*
- Image when `avatar_url` is set; initials fallback (first + last initial) per R28. Keep.
- **Presence dot slot:** compose an online/offline dot onto the avatar (bottom-right) rather than a separate labeled row, for use in DM lists, member lists, and the shell.
- **Adopt in the shell:** `UserMenu` currently renders a bare initial circle, so a user's real avatar never appears in nav — use `Avatar`.

### 3.5 Feedback — `AlertBanner` / `Toast`
- **`AlertBanner` (revise):** inline, in-flow messaging tied to a region of the page (form errors, the "you were removed" notice, the zero-admin frozen state). Keep the variant→ARIA-role mapping; move `warning`/`error`/`success` colors to the design-tokens §12 recipes (drop raw `amber-*/emerald-*/red-*`). Only **one** contextual banner should occupy a slot at a time (the review found up to four stacked on `ChannelPage`).
- **`Toast` (new):** transient, corner-anchored feedback for **background** outcomes (message send failed after leaving the view, invite sent, session revoked). Live-region backed; auto-dismiss with a manual close; `--z-toast`. Not for inline form validation.

### 3.6 Loading & empty — `Skeleton` / `EmptyState`
- **`Skeleton` (new):** the single loading treatment. Renders the *shape* of the final content (sidebar rows, table rows, timeline rows) so there is no layout jump when data arrives. Reduced-motion disables the shimmer (tokens §11). Replaces the bare "Loading…" text strings.
- **`EmptyState` (new):** icon + one-line explanation + a primary action. Every async list uses it: no channels joined (→ Browse/Create), empty public browse (→ Create the first channel), no DMs (→ New message), no invites, no users found. Copy comes from PRD §11.

### 3.7 Confirmation — `Confirm` (inline) / `Dialog`
- **One pattern** replacing the four dialects (leave-channel banner+button, self-demote inline text, message-delete inline links, user-deactivate inline). 
- **Inline confirm** (a small popover/inline swap with Confirm/Cancel) for reversible or low-stakes actions.
- **`Dialog`** (modal, focus-trapped) for destructive + hard-to-reverse actions (user deactivation, which drops sessions immediately).
- Both: destructive action uses `danger`; Cancel is always present and focusable; focus returns to the trigger on close (ACCESSIBILITY_GUIDELINES).

### 3.8 Overlays — `Drawer` / `Modal`
- **`Drawer`:** right-side slide-over at `--z-drawer` with a scrim; the **Channel details** panel (members, roles, add-member, leave) lives here (ADR-0015). Focus-trapped; Escape closes; returns focus to the opener.
- **`Modal`/`Dialog`:** centered at `--z-modal`; used sparingly (destructive confirms, the ⌘K switcher may use its own overlay).

### 3.9 Icons — `IconButton` + icon set
- Adopt **one 16/20px stroke set** (Lucide-class, self-hosted; no external CDN — CSP/offline). The app has three inline SVGs total today, a major reason it reads flat.
- Rule: **icons for object types** (`#` channel, lock private, paperclip attach, magnifier search, presence dot) and **repeated actions**; **text for one-off actions**. Every icon-only control is an `IconButton` with an `aria-label`.

### 3.10 Card — *keep, use sparingly*
- Elevation-2 surface for genuinely grouped content (auth panels, a settings section). Not the wrapper for empty states (use `EmptyState`), not the chat container (use the conversation surface, §5.3). When everything is a card, elevation stops signaling anything.

---

## 4. Composite patterns

### 4.1 Table / list pattern
- Header row in `text-caption` + `--color-text-tertiary`; data rows at `--row-height-table` with a hover state; row actions are `Button size="sm"` or `IconButton` (never a bespoke button).
- Timestamps use tabular numerals and short/relative formats (see UX_GUIDELINES), not `toLocaleString()` dumps.
- On `< md`, tables become **stacked cards** (§6), not horizontally scrolling grids.
- Empty → `EmptyState`; loading → `Skeleton` rows.

### 4.2 Sidebar navigation row
- Single line at `--row-height-nav`. Content order: object glyph (`#`/lock) · name (truncates) · optional trailing signal (unread dot, presence). **No two-line rows, no stacked pills** (the review flagged the current 56px two-badge rows). `hover` and `selected` states from tokens §13.

### 4.3 Message row (grouped timeline) — ADR-0015
- **Flat, left-aligned**, no per-message border box, no alignment flipping.
- **Grouping:** consecutive messages from one author within a short window share a single avatar + name + timestamp header; subsequent lines are indented under it.
- **Date separators** divide days.
- **Actions on hover/focus-within** (author edit/delete) — not standing chrome. Deleted → retained tombstone; edited → "(edited)" marker.
- Own messages show the user's real name in the same column as everyone else (no "You" special-casing now that alignment is uniform).

### 4.4 Composer
- `Textarea` + a bottom row: attach as an **`IconButton`** (paperclip), the character counter shown **only near the limit** (~90%+), and the Send `Button`. Enter sends, Shift+Enter newlines. Keep the existing optimistic-send, pending/failed, and rate-limit-countdown behavior — that part is good.

### 4.5 Channel details drawer — ADR-0015
- Opened from the conversation header's **Details** action. Contains: member list (with presence), role management (admin), add-member (via the user picker, ADR-0016), leave, and the zero-admin/frozen affordances. Everything that today stacks above the timeline moves here.

### 4.6 Page scaffold
- One `text-heading` per screen; sections use `text-subheading`; consistent vertical rhythm (`space-y-6` between sections). Contextual actions align to the heading row, not scattered.

---

## 5. Layout templates

### 5.1 App shell (authenticated) — ADR-0014
Persistent **left sidebar** (primary nav) + **contextual top bar** + **content region**. Sidebar sections top-to-bottom: workspace mark (links home) · search/⌘K · Channels · Direct messages · footer cluster (Settings, Admin [role-gated], account + theme). At `< md` the sidebar is a **drawer** toggled from a top-bar menu button; content never stacks below nav. Full structure in INFORMATION_ARCHITECTURE.md.

### 5.2 List / table screen
Heading + optional primary action → filters/search → table/list (with Skeleton/EmptyState) → pagination. Used by Browse channels, Invites, Users, Sessions.

### 5.3 Conversation surface — ADR-0015
Full height: header (name · member/presence summary · Details) → flexing timeline (grouped rows, date separators) → pinned composer. Shared by channels **and** DMs, parameterized by `ConversationTarget`. Members/admin live in the details drawer (5.1 of ADR-0015), never stacked above the timeline.

### 5.4 Auth / onboarding surface
`AuroraBackground` + centered `Card`, one `text-display` heading, form rhythm from design-tokens §5. The only place the ambient identity appears.

---

## 6. Responsive behavior

- **`≥ md`:** persistent sidebar; conversation surface full height; tables as tables.
- **`< md`:** sidebar → drawer; conversation surface is the whole screen (header/timeline/composer); the Channel details drawer becomes a full-screen sheet; **tables → stacked cards** (label:value pairs) so nothing depends on horizontal scroll.
- **`≥ lg`:** the Channel details drawer *may* be pinned open beside the timeline (optional, not required for v1).
- Use relative units and the density tokens; the body never scrolls horizontally — wide content (a rare code block) scrolls inside its own container.

---

## 7. Migration notes (what changes in existing code)

Executed by task-breakdown **M10** — this section maps components to their fate so nothing is redesigned twice:
- **De-duplicate:** delete `RoleBadge` (×2), `VisibilityBadge`, `StatusBadge`, and inline pills → `Badge` (T58). Extract `Textarea` (T59). Adopt `Avatar` in `UserMenu` (T65).
- **Button:** invert width default, add `sm` + `ghost`/`link` + link rendering; migrate all call sites off `w-auto` and off bespoke table buttons (T57).
- **Feedback/state:** `AlertBanner` colors → tokens §12; add `Skeleton` (T60), `EmptyState` (T61), `Confirm`/`Dialog` (T62), `Toast` (T63), icons/`IconButton` (T64).
- **Layout:** app shell (T66), conversation surface + timeline + composer (T70–T72), responsive tables (T77).
- `NotFoundPage` is re-skinned onto tokens and rendered in-shell (T67) — today it uses hardcoded `gray-900`/`indigo-600` and is unreadable in dark mode.

---

## 8. Do / don't (quick reference)

**Do:** compose primitives; reference token names; complete every state; use `Badge`/`Confirm`/`EmptyState`/`Skeleton` instead of re-implementing; put secondary controls in a drawer/hover; use `sm` controls in tables.

**Don't:** hardcode a hex/px/ms; hand-roll a button or pill; stack admin tools above a conversation; render raw `toLocaleString()` timestamps; leave a loading state as bare text; use `Card` as a universal wrapper; ship an icon-only control without an `aria-label`.
