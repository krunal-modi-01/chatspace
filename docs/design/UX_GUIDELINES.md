# chatspace UX Guidelines

> Owner: `product-manager` + `architect` (design). Status: **Proposed** (human design gate). Part of the design documentation set ([ADR-0013](../../architecture/adr/0013-design-documentation-structure.md)).
>
> Defines *philosophy and behavior* — the design vision, the principles that decide the cases this document does not enumerate, and the canonical interaction patterns. Values → [`design-tokens.md`](../../architecture/design-tokens.md); components → [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md); structure → [`INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md); a11y → [`ACCESSIBILITY_GUIDELINES.md`](ACCESSIBILITY_GUIDELINES.md). Extends PRD §11; does not restate it.

---

## 1. Design philosophy

**A calm, dense, fast workspace where the conversation is the interface and everything else gets out of the way.**

This extends the PRD's existing direction (premium, minimal, information-dense, closer to Linear/Raycast; ambient identity on auth only; single indigo accent; light + dark) rather than replacing it.

**What we borrow from mature tools** (the qualities, not the pixels — we are not cloning any of them):
- **Linear / Vercel** — near-monochrome surfaces with exactly one accent, crisp typography with tight heading tracking, purposeful density, instant feedback, restrained motion.
- **Slack** — unambiguous IA (you always know which channel you're in), the message list dominates, per-message chrome is near-zero, unread state is a first-class signal.
- **Notion / GitHub** — content-first calm, consistent spacing rhythm, hover-revealed controls, lists that *scan*, empty states that teach.
- **Raycast / Figma** — speed and keyboard as features; secondary information lives in panels/drawers off the primary surface, never stacked on top of it.

**Our distinct identity:** indigo-on-neutral with hairline structure and an aurora-lit entry, tuned to **comfortable** density — a notch roomier than Linear's densest tables, a notch tighter than a consumer chat app. A tool that feels precise and unhurried, recognizably itself, not a reskin of another product.

---

## 2. Principles

Each principle carries its rationale so it can be applied to situations not listed here.

1. **Content is the interface.** The primary surface of every screen owns the viewport; controls and metadata recede. *Why: primary-task dominance — the most frequent action should cost the least effort.* (Drives ADR-0015: the conversation, not administration, owns the channel screen.)
2. **One accent; color means something.** Indigo = action / selection / focus only. Every screen must read correctly in grayscale; color adds signal on top. *Why: decorative color destroys color's ability to signal state.*
3. **Purposeful density.** Use the density scale (tokens §6); compact but never cramped. *Why: density is legibility per glance — the goal is scanning, not minimalism for its own sake.*
4. **Progressive disclosure.** Secondary controls appear on hover/focus or in a drawer, not as standing chrome. *Why: disclosure proportional to relevance.* (Drives hover-revealed message actions and the details drawer.)
5. **Instant, honest feedback.** Optimistic updates, skeletons that match final shape, toasts for background outcomes; never a silent no-op, never a "loading" that isn't. *Why: perceived performance and trust.*
6. **Keyboard-first fluency.** Every primary action reachable without a mouse; a quick switcher (⌘K) as the spine. *Why: the fluency ceiling of a tool people live in all day.*
7. **One pattern per job.** One confirmation pattern, one empty-state pattern, one table treatment. *Why: consistency compounds — users learn the app once, not per screen.*
8. **Calm, motivated motion.** 150–200ms, purposeful, reduced-motion honored. *Why: motion is feedback, not decoration.*
9. **Legible hierarchy.** One heading per screen; ≤3 type sizes per view; weight and space create priority before color does. *Why: scanability.*
10. **Accessible by construction.** WCAG 2.2 AA (the adopted standard — see ACCESSIBILITY_GUIDELINES §1) is designed in, not audited on. *Why: cheaper and better than retrofitting — and the codebase already proves the team can do it.*

---

## 3. Interaction patterns (canonical)

One decided approach per interaction. Components implementing these live in DESIGN_SYSTEM.md.

### 3.1 Confirmation
- **Reversible / low-stakes** (leave channel, delete own message, demote self, revoke invite) → **inline `Confirm`** (in-place Confirm/Cancel). Destructive action styled `danger`; Cancel always present.
- **Destructive + hard-to-reverse** (deactivate a user — drops their sessions immediately) → **`Dialog`** (modal, focus-trapped, returns focus to the trigger).
- Never more than one confirmation dialect in the app. This replaces the four the review found.

### 3.2 Loading
- **Skeleton-first.** Show a skeleton of the final shape (sidebar rows, table rows, timeline rows) — never a bare "Loading…" string, which causes layout jump and reads as prototype-grade.
- **Optimistic where safe.** Message send renders immediately as pending, reconciles by id (keep the current good behavior). Navigation shows the destination's skeleton, not a blank.
- **In-flight controls** show `isLoading` (spinner + `loadingText`), never a silently disabled button.

### 3.3 Empty states
- Every async list uses `EmptyState`: icon + one line + a primary action that resolves it. Copy from PRD §11 (no channels joined, empty browse, no DMs, no invites, no users found, no sessions). An empty state is an onboarding opportunity, not an error.

### 3.4 Error states
- **Inline, in-context** (form/action errors) → `AlertBanner`, mapping RFC 7807 `problem+json` (title → lead, detail → body; `correlation_id` shown only in dev). Specific mappings the specs call out keep their exact copy (409 already-registered, 502 email-undeliverable, 409 zero-admin frozen, 409 last-active-admin, 410 stale invite/reset). One banner per slot.
- **Background outcomes** (a send that failed after you navigated away, a session revoked elsewhere) → **`Toast`**.
- **Recovery is always offered:** retry, request-a-new-link, re-login, or a route back — never a dead end. Account-deactivated and session-expired get specific messages, not a generic login failure.

### 3.5 Forms
- **Validate at the right time:** inline on blur/submit; when a rule is stated as a hint (password "≥6 chars, a letter and a digit"), validate against that rule inline rather than only on server rejection.
- **Password fields** offer a reveal toggle.
- **Locked fields** (invited email, immutable username/email) are visibly disabled with a reason, not silently uneditable.
- **Uniform, non-enumerating responses** (reset request, invite redemption) render the same confirmation regardless of existence (F11/F15) — never expose which field or account was wrong.

### 3.6 Live updates
- New messages/edits/deletes render **in place** without refresh; dedup by id (existing WS contract). Announce via ARIA live regions (ACCESSIBILITY_GUIDELINES) without stealing focus.
- **Membership loss while viewing** (`channel.member_removed` for the open channel) exits the surface gracefully with the specific "you were removed from this channel" message and a route back (F75) — not a silent disappearance or a generic error.
- **Reconnecting** shows the reconnecting banner only while a previously-open connection is down (keep current behavior); it never lingers over a healthy socket.

### 3.7 Timestamps & numeric display
- **Relative** for recency ("2 min ago", "yesterday"), **absolute short** on hover/for older items ("Jul 14, 3:41 PM") — never raw `toLocaleString()` dumps. Tabular numerals (tokens §4) for aligned columns and counters.

---

## 4. Motion guidelines

- **Durations:** `--motion-fast` (150ms) for hover/focus/press; `--motion-base` (200ms) for entrances (drawer, toast, popover). Easing `ease-out`.
- **What animates:** state changes only — focus ring in, drawer/toast slide, press `active:scale-[0.98]`, theme cross-fade. Nothing animates without a state change to justify it.
- **New-message affordance:** a "↓ new messages" pill + smooth scroll-to-bottom when the user is scrolled up and a message arrives — motion that serves orientation, not decoration.
- **Reduced motion (hard requirement):** under `prefers-reduced-motion: reduce`, disable transforms, slides, and skeleton shimmer; keep instantaneous opacity/color so no feedback is lost (tokens §11, WCAG 2.3.3).

---

## 5. Navigation principles

- **Primary nav is always present** (persistent sidebar `≥ md`, drawer `< md`) — never hidden behind a click on desktop (INFORMATION_ARCHITECTURE.md, ADR-0014).
- **Location is always clear** — active sidebar row + section, mirrored by the top-bar title.
- **Keyboard-first** — ⌘K quick switcher is the fastest path to any conversation; every primary action has a keyboard route.
- **No dead ends, no orphans** — every empty state cross-links forward; every role-appropriate route is reachable by click (R58).
- **Rooms vs people** — Channels and DMs stay distinct sections (ADR-0017); do not merge into one list.

---

## 6. Content & microcopy

- **One heading per screen**; sentence case; name the screen for what it is.
- **Labels are consistent** — one term per concept across nav, headings, and buttons.
- **Copy is plain and specific** — errors say what happened and what to do; empty states say what this is and how to fill it. Avoid jargon and cleverness.
- **Destructive actions name their consequence** ("Deactivate — this signs the user out of all sessions immediately").

---

## 7. Density philosophy

Comfortable, not maximal (tokens §1/§6). Prefer showing more real content over more whitespace, but never at the cost of a 44px touch target or a legible line. When a screen feels cramped, the fix is usually *fewer elements* (drop a redundant badge, move a control to a drawer), not more padding. When it feels empty, the fix is usually *the right primary content*, not filler cards.
