# chatspace Design Tokens (v3)

> Owner: `architect` (proposed) / human design sign-off pending. Referenced by PRD §11 ("Visual tone / reference product"), required input for `frontend-engineer`, and the **single source of design _values_** per [ADR-0013](adr/0013-design-documentation-structure.md). This file defines values only (color, type, space, density, radius, elevation, motion, z-index, breakpoints). *Components, layout, and usage* are defined in [`docs/design/DESIGN_SYSTEM.md`](../docs/design/DESIGN_SYSTEM.md), which references these names and never restates a value. Utility classes are applied through the shared primitives in `frontend/src/components/ui/`, not invented per page.
>
> **v3 supersedes v2.** v2 established semantic color, dark mode, a type scale, elevation, and motion. v3 keeps all of that verbatim and adds what the 2026-07-20 UX review found missing: a **font family** (the app currently renders in the OS default), a **density scale**, a **z-index scale**, **breakpoints**, **badge-tint and focus-ring recipes**, and **reduced-motion** guidance. It also states the single-definition rule (§15) that keeps this file and the design docs from drifting.

## 1. Tone

Premium, minimal, information-dense in the working app (closer to Linear/Raycast than a marketing site). A distinctive ambient identity is reserved for low-density, first-impression surfaces (auth/onboarding) via soft gradient/noise backgrounds — the working app itself (nav, dashboard, channel/message views) stays a near-flat neutral surface where legibility and density win over atmosphere. No illustration/imagery beyond avatars. Both light and dark themes are supported; default to system preference, user-toggleable, persisted to `localStorage`.

Density target: **comfortable**, not maximal — a notch more breathing room than Linear's densest tables, a notch tighter than a consumer chat app. The product should feel precise and unhurried.

## 2. Color — semantic tokens (CSS variables, themed)

Define as CSS custom properties on `:root` (light) and `.dark` (dark), consumed via Tailwind's `dark:` variant (class-based, see §10). Do not hardcode raw Tailwind grays/colors in components — use the semantic names below.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-surface` | `#ffffff` | `#0b0d12` | Page background |
| `--color-surface-raised` | `#f8f9fb` | `#12151c` | Sidebar, header, secondary panels |
| `--color-surface-overlay` | `#ffffff` | `#181c25` | Cards, popovers, modals (one step lighter than raised in dark) |
| `--color-border` | `#e5e7eb` | `#242833` | Hairline borders (1px) — replaces shadows for depth in dark |
| `--color-text-primary` | `#0f1115` | `#f2f3f5` | Headings, primary content |
| `--color-text-secondary` | `#5b6472` | `#9aa2b1` | Body/secondary text |
| `--color-text-tertiary` | `#8a93a3` | `#6b7280` | Captions, timestamps, placeholders |
| `--color-accent` | `#4f46e5` (indigo-600) | `#818cf8` (indigo-400) | Primary actions, links, focus |
| `--color-accent-hover` | `#4338ca` (indigo-700) | `#a5b4fc` (indigo-300) | Hover on accent |
| `--color-success` | `#059669` | `#34d399` | Success states |
| `--color-warning` | `#d97706` | `#fbbf24` | Warning states |
| `--color-danger` | `#dc2626` | `#f87171` | Error/destructive states |

Reserve color for meaning (state, action, emphasis), not decoration. A screen should read correctly in grayscale; color adds signal on top. **One accent** — indigo is for action, selection, and focus only. Tinted status backgrounds (badges, banners) are **derived** from these tokens, never from raw Tailwind palettes — see §12.

## 3. Ambient background system (auth/onboarding surfaces only)

Applied via a single `<AuroraBackground>` wrapper, not repeated per page:
- Two to three large (60–80vh), low-opacity (12–18%) radial gradient blobs in accent/violet hues, positioned off-axis (not centered/symmetrical — avoids a "spotlight" look), rendered behind content with `blur` and fixed positioning.
- A fixed, very low-opacity (2–3%) SVG noise/grain overlay on top of the gradient to avoid banding and add tactile texture.
- Never applied to the working app shell (dashboard, nav, dense content) — those stay flat per §1.

## 4. Typography

**Font family (new in v3).** The app must ship a real typeface, not the OS default. Self-host a variable sans in the Inter/Geist class; expose it as a token and apply it on `body`.

| Token | Value | Use |
|---|---|---|
| `--font-sans` | `'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif` | All UI text (default on `body`) |
| `--font-mono` | `'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace` | Correlation ids (dev), code, fixed-width data |

`'Inter Variable'` / `'JetBrains Mono Variable'` are the actual family names shipped by the self-hosted `@fontsource-variable` packages (not the generic `'Inter var'` placeholder used above pre-v3); listed first so the loaded local font wins, with the rest of the fallback chain unchanged.

- **Tabular numerals:** apply `font-variant-numeric: tabular-nums` to timestamps, counters, member counts, and any aligned numeric column — expose as a `.nums-tabular` utility.
- **Heading tracking:** headings (`text-display`, `text-heading`) use `letter-spacing: -0.01em`; body/caption use default tracking.

| Token | Size / weight / line-height | Use |
|---|---|---|
| `text-display` | 2rem / 600 / 1.2 | Auth screen headline only (one per flow) |
| `text-heading` | 1.25rem / 600 / 1.3 | Page-level heading in the app shell |
| `text-subheading` | 0.9375rem / 600 / 1.4 | Section headings |
| `text-body` | 0.875rem / 400 / 1.5 | Default body/label/input text |
| `text-caption` | 0.75rem / 400 / 1.4 | Helper text, timestamps, metadata |

One heading per screen. Don't mix more than 3 text sizes on a single view.

## 5. Spacing & radius

- **Spacing:** Tailwind's default 4px scale. Form field rhythm: `space-y-4` between fields, `space-y-6` between form and surrounding content.
- **Radius:** `--radius-md: 10px` (inputs, buttons, badges), `--radius-lg: 16px` (cards, modals, drawers), `--radius-full: 9999px` (avatars, presence dots, pills) — soft, not boxy.

## 6. Density scale (new in v3)

The review found tables hand-rolling smaller buttons because no density scale existed. Codify control and row heights so components share one rhythm.

| Token | Value | Use |
|---|---|---|
| `--control-height-sm` | `1.75rem` (28px) | Compact controls inside tables/rows (`Button size="sm"`, inline actions) |
| `--control-height-md` | `2.25rem` (36px) | Default controls in forms (`Button size="md"`, `Input`, `Select`) |
| `--row-height-table` | `2.5rem`–`2.75rem` (40–44px) | Table/list data rows |
| `--row-height-nav` | `2rem` (32px) | Sidebar navigation rows (single line) |
| `--icon-sm` / `--icon-md` | `1rem` (16px) / `1.25rem` (20px) | Icon sizes (see §14 iconography) |

Sidebar rows are **single-line** at `--row-height-nav`; the channel name is the primary content, visibility is a glyph, and role is shown only where it matters (not in the nav list). See DESIGN_SYSTEM.md for the row spec.

## 7. Elevation (depth without heavy shadows)

| Layer | Light | Dark |
|---|---|---|
| Base (page) | `--color-surface` | `--color-surface` |
| Raised (sidebar/header) | `--color-surface-raised` + `1px solid --color-border` | same, border does the work — no shadow |
| Overlay (card/popover/modal/drawer) | `--color-surface-overlay` + `shadow-sm` | `--color-surface-overlay` + `1px solid --color-border` (shadows don't read on dark; border carries the separation) |

## 8. Z-index scale (new in v3)

One ladder for stacking; components reference these names, never ad-hoc integers.

| Token | Value | Use |
|---|---|---|
| `--z-base` | `0` | In-flow content |
| `--z-dropdown` | `1000` | Menus, popovers, select lists |
| `--z-sticky` | `1100` | Sticky headers / composer |
| `--z-drawer` | `1200` | Slide-over drawer + its scrim |
| `--z-modal` | `1300` | Modal dialog + scrim |
| `--z-toast` | `1400` | Toast/notification layer |
| `--z-tooltip` | `1500` | Tooltips (always on top) |

## 9. Breakpoints (new in v3)

Documented for reference; Tailwind v4 provides the utilities. The **`md` (768px)** breakpoint is the app-shell switch: sidebar is persistent at `≥ md`, a drawer below it (ADR-0014).

| Token | Value | Note |
|---|---|---|
| `--bp-sm` | `640px` | Small phones → large phones |
| `--bp-md` | `768px` | **Sidebar ↔ drawer switch** |
| `--bp-lg` | `1024px` | Tablet → desktop; details drawer may become persistent |
| `--bp-xl` | `1280px` | Wide desktop |

## 10. Theming mechanism

Class-based dark mode: `<html class="dark">` toggled by a theme switcher, defaulting to `prefers-color-scheme` on first load, persisted to `localStorage`. Tailwind v4: declare `@custom-variant dark (&:where(.dark, .dark *));` in `index.css` so `dark:` variants key off the class, not only the media query. Never rely on `color-scheme: light dark` alone to drive component appearance — every surface must have an explicit light/dark value, or components silently break under system dark mode (the bug that motivated the v2 revision).

## 11. Motion

- Transitions: 150–200ms `ease-out` on hover/focus/theme-switch. Expose `--motion-fast: 150ms` and `--motion-base: 200ms`.
- Buttons: `active:scale-[0.98]` press feedback.
- Inputs: focus ring transitions in, not instant.
- No motion without a state change to justify it (focus, load, success, error, theme switch).
- **Reduced motion (new in v3):** honor `@media (prefers-reduced-motion: reduce)` — disable transforms (`scale`, slide-in), skeleton shimmer, and drawer/toast slide animations; keep instantaneous opacity/color changes so feedback is not lost. This is a **hard requirement**, not optional polish (WCAG 2.2 §2.3.3; see ACCESSIBILITY_GUIDELINES.md).

## 12. Semantic recipes (new in v3)

Derived treatments that components must use instead of importing raw Tailwind palette classes.

**Badge / tinted-status surfaces** — one recipe per semantic color, so status chips follow theme automatically:
```
background: color-mix(in srgb, var(--color-<semantic>) 12%, transparent);
color:      color-mix(in srgb, var(--color-<semantic>) 70%, <on-tint-blend>);
```
where `<semantic>` ∈ { `accent`, `success`, `warning`, `danger` } and `<on-tint-blend>` is black in light theme / white in dark theme (exposed as `--tint-text-blend`, themed alongside the `--color-*` tokens in §2). The raw semantic color alone fails WCAG AA 1.4.3 (4.5:1) as text over a 12%-mix background in light theme (measured 2.8:1–4.0:1) — blend it 70% toward the on-tint-blend color instead of using it raw. Plus a `neutral` variant using `--color-surface-raised` background + `--color-text-secondary` text. This replaces the six hand-rolled `amber-*/emerald-*/red-*/gray-*` badge implementations the review found.

`AlertBanner`'s implementation of this recipe (`.tint-surface` in `frontend/src/index.css`) also sets a `border-color: color-mix(in srgb, var(--color-<semantic>) 24%, transparent)` — a reasonable extension for a bordered banner surface. A plain `Badge`/pill (T58) typically has no visible border and can omit it; carry it forward only if the pill design calls for one.

**Focus ring** — one convention for every focusable element:
```
--focus-ring-width: 2px;
--focus-ring-color: var(--color-accent);
```
- On **filled/standalone** controls (buttons, links): 2px ring with `2px` offset against the surrounding surface (`ring-offset`).
- On **inset** controls (inputs, table-row actions): 2px ring with `0` offset.
- Always `:focus-visible`, never a bare `:focus` that fires on mouse click; never remove the outline without replacing it.

## 13. Component states (required for every interactive primitive)

Every `Button`, `Input`, `Link`-as-action, and every new primitive must define: `default`, `hover`, `focus-visible` (the §12 ring, both themes), `disabled` (reduced opacity + `cursor-not-allowed`), and where applicable `loading` (spinner or skeleton, never a silent no-op). Row-level components (nav rows, table rows) additionally define `hover` and `selected`.

## 14. Shared primitives (required, not optional)

Before building a new screen, `frontend-engineer` must check `frontend/src/components/ui/` for existing primitives and reuse them; if one doesn't exist yet, build it there first. Full specs (variants, props, states, a11y) live in DESIGN_SYSTEM.md; this is the required inventory:

**Existing (keep, some to be revised — see DESIGN_SYSTEM.md):**
- `Button` (variants: `primary`, `secondary`, `danger`, **`ghost`**, **`link`**; **sizes `sm`/`md`**; `fullWidth` opt-in; `isLoading`) — *revised in v3: intrinsic width by default, size + variant additions*
- `Input` / `FormField` (label + input + inline error, wired for `aria-describedby`)
- `Select`
- `Card` (elevation-2 container per §7)
- `AlertBanner` (variants: `info`, `warning`, `error`, `success` — colors from §12, not raw palettes)
- `Avatar` (image or initials fallback per R28; **presence-dot slot** in v3)
- `AuroraBackground` (ambient gradient+noise wrapper, auth/onboarding surfaces only, §3)
- `ThemeToggle` (light/dark switch, persists preference)

**New in v3 (build in `ui/` before the screens that need them):**
- `Badge` (variants: `neutral`, `accent`, `success`, `warning`, `danger`) — replaces all inline pills
- `Textarea` (shared by composer, message edit, add-member)
- `Skeleton` (loading placeholder; reduced-motion aware)
- `EmptyState` (icon + line + primary action)
- `Confirm` (inline confirm for reversible actions; `Dialog`-based only for destructive+irreversible)
- `Toast` (background success/failure notifications; live-region backed)
- `IconButton` + an adopted **stroke icon set** (16/20px, §6)
- `Drawer` / `Modal` (slide-over + centered dialog; use `--z-drawer` / `--z-modal`)

## 15. Consuming tokens — the single-definition rule (new in v3)

Per [ADR-0013](adr/0013-design-documentation-structure.md):
- **This file is the only place a raw value is defined.** A hardcoded hex, px size, or duration anywhere in components or in the other design docs is a defect caught in review.
- Components reference token **names** (`var(--color-*)`, the density/z/motion tokens, the §12 recipes). DESIGN_SYSTEM.md, INFORMATION_ARCHITECTURE.md, and UX_GUIDELINES.md reference these names and never restate a value.
- Tailwind v4 wiring: tokens live in `@theme` / `:root` / `.dark` in `frontend/src/index.css`; the typography scale is exposed as named `@utility` classes (`text-display`…`text-caption`) so size/weight/line-height travel together.

## 16. Status

Directed by explicit human design decision (2026-07-08, extended 2026-07-20); supersedes the v1 "utilitarian, light-only" default and the v2 baseline. Treat as authoritative for v1 unless overridden again via a design ADR. Consuming documents: DESIGN_SYSTEM.md, INFORMATION_ARCHITECTURE.md, UX_GUIDELINES.md, ACCESSIBILITY_GUIDELINES.md.
