# chatspace Design Tokens (v2)

> Owner: `architect` (proposed) / human design sign-off pending. Referenced by PRD §11 ("Visual tone / reference product") and required input for `frontend-engineer` (see agent definition). This is the visual system every screen must draw from — utility classes should be applied through the shared primitives in `frontend/src/components/ui/`, not invented per page.
>
> **v2 supersedes v1.** v1 assumed light-mode-only and a flat utilitarian look throughout. Human direction (2026-07-08) explicitly requested a premium, distinctive identity with atmosphere/depth and both light and dark themes — this version reflects that.

## 1. Tone

Premium, minimal, information-dense in the working app (closer to Linear/Raycast than a marketing site). A distinctive ambient identity is reserved for low-density, first-impression surfaces (auth/onboarding) via soft gradient/noise backgrounds — the working app itself (nav, dashboard, future channel/message views) stays a near-flat neutral surface where legibility and density win over atmosphere. No illustration/imagery beyond avatars. Both light and dark themes are supported; default to system preference, user-toggleable, persisted to `localStorage`.

## 2. Color — semantic tokens (CSS variables, themed)

Define as CSS custom properties on `:root` (light) and `.dark` (dark), consumed via Tailwind's `dark:` variant (class-based, see §7). Do not hardcode raw Tailwind grays in components — use the semantic names below.

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

Reserve color for meaning (state, action, emphasis), not decoration. A screen should read correctly in grayscale; color adds signal on top.

## 3. Ambient background system (auth/onboarding surfaces only)

Applied via a single `<AuroraBackground>` wrapper, not repeated per page:
- Two to three large (60–80vh), low-opacity (12–18%) radial gradient blobs in accent/violet hues, positioned off-axis (not centered/symmetrical — avoids a "spotlight" look), rendered behind content with `blur` and fixed positioning.
- A fixed, very low-opacity (2–3%) SVG noise/grain overlay on top of the gradient to avoid banding and add tactile texture.
- Never applied to the working app shell (dashboard, nav, dense content) — those stay flat per §1.

## 4. Typography

| Token | Size / weight / line-height | Use |
|---|---|---|
| `text-display` | 2rem / 600 / 1.2 | Auth screen headline only (one per flow) |
| `text-heading` | 1.25rem / 600 / 1.3 | Page-level heading in the app shell |
| `text-subheading` | 0.9375rem / 600 / 1.4 | Section headings |
| `text-body` | 0.875rem / 400 / 1.5 | Default body/label/input text |
| `text-caption` | 0.75rem / 400 / 1.4 | Helper text, timestamps, metadata |

One heading per screen. Don't mix more than 3 text sizes on a single view.

## 5. Spacing & radius

- Spacing: Tailwind's default 4px scale. Form field rhythm: `space-y-4` between fields, `space-y-6` between form and surrounding content.
- Radius: `--radius-md: 10px` (inputs, buttons), `--radius-lg: 16px` (cards, modals) — soft, not boxy.

## 6. Elevation (depth without heavy shadows)

| Layer | Light | Dark |
|---|---|---|
| Base (page) | `--color-surface` | `--color-surface` |
| Raised (sidebar/header) | `--color-surface-raised` + `1px solid --color-border` | same, border does the work — no shadow |
| Overlay (card/popover/modal) | `--color-surface-overlay` + `shadow-sm` | `--color-surface-overlay` + `1px solid --color-border` (shadows don't read on dark; border carries the separation) |

## 7. Theming mechanism

Class-based dark mode: `<html class="dark">` toggled by a theme switcher, defaulting to `prefers-color-scheme` on first load, persisted to `localStorage`. Tailwind v4: declare `@custom-variant dark (&:where(.dark, .dark *));` in `index.css` so `dark:` variants key off the class, not only the media query. Never rely on `color-scheme: light dark` alone to drive component appearance — every surface must have an explicit light/dark value, or components silently break under system dark mode (the bug that motivated this revision).

## 8. Motion

- Transitions: 150–200ms `ease-out` on hover/focus/theme-switch.
- Buttons: `active:scale-[0.98]` press feedback.
- Inputs: focus ring transitions in, not instant.
- No motion without a state change to justify it (focus, load, success, error, theme switch).

## 9. Component states (required for every interactive primitive)

Every `Button`, `Input`, and `Link`-as-action must define: `default`, `hover`, `focus-visible` (visible ring using `--color-accent`, both themes), `disabled` (reduced opacity + `cursor-not-allowed`), and where applicable `loading` (spinner or skeleton, never a silent no-op).

## 10. Shared primitives (required, not optional)

Before building a new screen, `frontend-engineer` must check `frontend/src/components/ui/` for existing primitives and reuse them; if one doesn't exist yet, build it here first:

- `Button` (variants: `primary`, `secondary`, `danger`; supports `isLoading`)
- `Input` / `FormField` (label + input + inline error, wired for `aria-describedby`)
- `Card` (elevation-2 container per §6)
- `AlertBanner` (variants: `info`, `warning`, `error`, `success`)
- `AuroraBackground` (ambient gradient+noise wrapper, auth/onboarding surfaces only, §3)
- `ThemeToggle` (light/dark switch, persists preference)

## 11. Status

Directed by explicit human design decision (2026-07-08); supersedes the v1 "utilitarian, light-only" default. Treat as authoritative for v1 unless overridden again.
