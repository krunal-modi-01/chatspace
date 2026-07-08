---
name: frontend
description: UI implementation — component structure and composition, state management (local/server/global), data fetching and caching, forms and validation, and client performance (bundle size, render cost, Core Web Vitals). Use when building or reviewing UI components, wiring client-server data flow, handling forms/validation, or diagnosing slow/janky/heavy front-ends. Used by the frontend-engineer agent. Stack-agnostic — detect the framework (React/Vue/Svelte/Angular/etc.) from the project.
---
# Frontend Skill

## Purpose
Build UI that is correct, accessible, and fast: components that compose cleanly, state that lives in exactly one place, data fetching that handles loading/error/empty honestly, and a bundle that ships only what the user needs. Perceived performance and correct handling of async states are first-class, not afterthoughts.

## When invoked
- The **frontend-engineer** agent uses this when implementing screens, components, forms, or client-side data flow, and when investigating slow renders, large bundles, or poor Core Web Vitals.
- Triggered by: "build the … page/component", "wire this up to the API", "add a form for …", "the page is slow / janky / huge", "handle the loading/error state".
- Pairs with `api-design` (the contract it consumes), `testing`, `accessibility` (accessibility-auditor), and `performance` (performance-engineer).

## Inputs
- Designs/mockups and interaction specs; content and states (loading, empty, error, partial).
- The API contract (endpoints, shapes, error formats, pagination) from `api-design`.
- Non-functional targets: Core Web Vitals budgets (LCP, INP, CLS), bundle-size budget, target devices/networks.
- Existing conventions: framework, component library, state/data-fetching libraries, styling approach.

## Outputs
- Components with a clear split between presentational (props in, events out) and container/state-holding concerns.
- State classified and placed correctly: server-cache vs client UI state vs URL state vs global.
- Data fetching that renders every async state (loading, error, empty, success) and handles refetch/invalidation.
- Forms with validation, accessible error messaging, and controlled submission (no double-submit).
- A bundle within budget: code-split, lazy-loaded, tree-shaken; assets optimized.

## Procedure
0. **Reuse or create shared visual primitives before per-page markup.** Check the project's shared UI directory (e.g. `components/ui/`) for existing `Button`/`Input`/`Card`/`AlertBanner`-style primitives sourced from the project's design tokens. If none exist for something the screen needs, build the primitive first and use it — never inline one-off utility classes on a page that duplicate what a shared primitive should own. This is what keeps screens visually consistent as more get built.
1. **Break the UI into components by responsibility**, not by visual coincidence. Prefer small, composable, presentational components (data in via props, changes out via callbacks) wrapped by a few container components that own state and side effects. This keeps the leaves reusable and testable.
2. **Classify state before writing it.** Distinguish: (a) **server state** — data owned by the backend, fetched and cached (use a data-fetching/cache library; treat it as a cache, not local state); (b) **UI state** — transient, local to a component (open/closed, hover); (c) **URL state** — anything that should survive refresh/share (filters, tab, page); (d) **global client state** — genuinely cross-cutting (theme, auth). Put each in exactly one place. Lift state only as high as needed; colocate the rest.
3. **Never store derived data in state.** Compute it during render (memoize only if measured to be expensive). Duplicated/derived state is the #1 source of UI inconsistency bugs.
4. **Fetch data declaratively and render all four async states.** For every fetch, design the loading, error, empty, and success UI up front. Handle refetch, cache invalidation on mutation, and stale data. Avoid waterfalls — parallelize independent requests; prefetch on intent (hover/route) where it helps.
5. **Guard against race conditions** in async effects: cancel or ignore stale responses (abort controller / request-id check) so a fast second request can't be overwritten by a slow first one.
6. **Build forms deliberately.** Validate on the right trigger (on-blur / on-submit, not aggressively on every keystroke). Show accessible, specific error messages tied to inputs (label + `aria-describedby`). Disable/guard the submit button to prevent double-submission; reflect server-side validation errors back onto fields. Keep the form's source of truth in one place.
7. **Budget the bundle.** Measure it. Code-split by route and lazy-load heavy/rarely-used chunks. Ensure tree-shaking works (side-effect-free modules, no barrel imports pulling in the world). Prefer smaller dependencies; audit before adding a library. Import icons/components granularly.
8. **Optimize rendering.** Avoid unnecessary re-renders: stable references for props/callbacks, correct keys in lists, virtualization for long lists. Reach for memoization (`memo`/`useMemo`/`computed`) only after profiling shows a real cost — premature memoization adds noise and bugs.
9. **Protect Core Web Vitals.** LCP: prioritize the hero image/content, use responsive images and modern formats, avoid render-blocking resources. CLS: reserve space for images/embeds/fonts (width/height, `font-display`), never inject content above existing content. INP: keep event handlers light, defer/break up heavy work, avoid long tasks on the main thread.
10. **Handle errors and boundaries.** Use error boundaries so one broken component doesn't blank the whole app. Show actionable error UI with retry. Never leave the user staring at a spinner forever — always have a timeout/error path.
11. **Verify accessibility and test.** Semantic HTML first, ARIA only to fill gaps; keyboard-navigable; visible focus. Hand off to `accessibility` for audit. Test components (render + interaction), and test the loading/error/empty states, not just the happy path — hand to `testing`.

## Best practices
- One source of truth per piece of state; derive everything else.
- Treat server data as a cache with a library that handles caching, dedup, and invalidation — don't hand-roll it in global state.
- Design the loading/error/empty states with the same care as the success state.
- Semantic HTML and keyboard support by default; measure a11y, don't assume it.
- Measure before optimizing — profile renders and inspect the bundle; ship budgets in CI.
- Keep components small and props explicit; prefer composition over configuration flags.

## Anti-patterns
- **Derived state stored in useState/refs** — goes stale, causes inconsistency.
- **Prop drilling deep trees** or, conversely, dumping everything into global state — both couple unrelated code. Use context/composition where appropriate.
- **Only building the happy path** — no loading, no error, no empty state.
- **Race conditions in fetch effects** — stale slow response overwrites the correct one.
- **Aggressive per-keystroke validation** that fights the user; or submitting a form with no double-submit guard.
- **Barrel imports and giant dependencies** that defeat tree-shaking and blow the bundle budget.
- **Premature memoization everywhere** — noise, subtle bugs, and no measured benefit.
- **Layout shift** from unsized images/ads/fonts injected after paint.
