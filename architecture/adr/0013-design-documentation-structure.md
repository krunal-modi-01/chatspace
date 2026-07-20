# ADR-0013: Design documentation structure

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-20
- **Deciders:** product-manager + architect + human design gate
- **Tags:** documentation, design-system, process

## Context
A design/UX review (2026-07-20) found the working app reads as "generic" and disconnected — not because the token layer is weak (`architecture/design-tokens.md` is a faithful implementation) but because there is **no document above the task list that describes how the product should look, navigate, and behave as a whole.** Design guidance is smeared across PRD §11 (visual tone + screen inventory + UX states), three task descriptions (T36/T47/T52 for accessibility), and code comments (the navigation-placement decision was made ad hoc inside T50). No spec references `design-tokens.md`; no design decision is recorded in any ADR; the UI was built ticket-by-ticket and looks like the ticket order.

The forcing question: **where does design guidance live, and how do the design documents relate so they extend the PRD/SPEC without duplicating or contradicting them or each other?**

A naive answer — "create one document per topic the review named" (UX guidelines, design system, IA, component guidelines, layout guidelines, interaction patterns, accessibility) — produces seven documents with 70%+ overlap and guarantees the drift the review is trying to end.

## Decision
We will establish a **layered design documentation set with a single-definition rule and a one-directional dependency**, and place the new documents under **`docs/design/`**.

1. **`architecture/design-tokens.md`** (expanded, kept at its current path to preserve existing references from the PRD and agent definitions) is the **only** place raw design *values* are defined — color, typography, spacing, density, radius, elevation, motion, z-index, breakpoints. Nothing else defines a hex code, size, or duration.
2. **`docs/design/DESIGN_SYSTEM.md`** defines *components and layout* built strictly from tokens — primitive inventory, variants, states, usage rules, layout templates, and responsive behavior. It never restates a token value; it references token names. (This absorbs the review's proposed COMPONENT_GUIDELINES and LAYOUT_GUIDELINES — components and their layout cannot be specified apart without duplication.)
3. **`docs/design/INFORMATION_ARCHITECTURE.md`** defines *composition* — the navigation model, sitemap, routing, sidebar structure, and per-screen information hierarchy.
4. **`docs/design/UX_GUIDELINES.md`** defines *philosophy and behavior* — design principles, interaction patterns (confirmation, loading, empty, error), motion behavior, and navigation principles. (This absorbs the review's proposed INTERACTION_PATTERNS — patterns are the applied form of the principles.)
5. **`docs/design/ACCESSIBILITY_GUIDELINES.md`** is the cross-cutting standard the other three reference but never restate.

**Dependency direction (never circular):** `design-tokens.md` ← `DESIGN_SYSTEM.md` ← (`INFORMATION_ARCHITECTURE.md`, `UX_GUIDELINES.md`); `ACCESSIBILITY_GUIDELINES.md` is referenced by all three. The **PRD** stays the product source of truth and points *down* into these docs for the "how"; the **SPEC** set stays behavior/contract and points at them for UX-state realization.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — layered set: expand tokens + 4 new docs, single-definition rule | Ends the scatter with one source per concern; the dependency direction makes contradictions structurally hard; matches how the review scoped the gap | Four new files to keep current; requires discipline to not restate values |
| B — one mega "DESIGN.md" | Single file, nothing to cross-reference | Becomes unmaintainable; mixes values, components, IA, a11y at different change cadences; merge-conflict magnet |
| C — all seven documents the review named individually | Maximal separation of topics | 70%+ overlap between component/layout/interaction docs → the exact duplication/drift the effort is meant to end |
| D — keep everything in PRD §11 | No new files | §11 already overloaded; a product doc is the wrong altitude for token/component detail; leaves IA unowned as it is today |

## Consequences
- **Positive:** One authoritative source per concern; new screens are built by *reading* the system, not reinventing it. Cross-references resolve in one direction, so a change to a token propagates by reference rather than by copy. The PRD/SPEC stop carrying design detail at the wrong altitude.
- **Negative / trade-offs:** Four new documents to maintain, and contributors must respect the single-definition rule (enforced in review: a raw hex/size/duration outside `design-tokens.md` is a defect). Three documents the review named are deliberately *not* created; if one section later outgrows its host, it is split out via a follow-up ADR, not silently.
- **Follow-ups:** Expand `design-tokens.md`; author the four `docs/design/` documents; add doc pointers to PRD §11 and TSD §3; the redesign milestone (task-breakdown M10) executes against them.

## Compliance / reversibility
Fully reversible — documentation only, no code or schema. No regulatory implication. Supersedes nothing; it formalizes and relocates guidance that until now lived implicitly. `design-tokens.md` intentionally stays at `architecture/` (not moved into `docs/design/`) so existing path references in the PRD and `.claude/agents/*` do not break.
