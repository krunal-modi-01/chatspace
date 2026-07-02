---
name: adr-authoring
description: Writing Architecture Decision Records — capturing context, the decision, options considered, and consequences, plus managing the ADR index and status lifecycle. Use when a significant, hard-to-reverse, or cross-cutting technical decision is made and should be recorded for future engineers. Used by the architect and documentation-writer agents. References templates/adr.md.
---

# ADR Authoring Skill

## Purpose
Record *why* significant technical decisions were made — so future engineers (and agents) understand the reasoning, not just the result, and don't relitigate settled questions or unknowingly violate constraints.

## When invoked
A decision that is **significant** (shapes structure/cost/risk), **hard to reverse**, or **cross-cutting** (affects multiple teams/components). Not for routine choices. Used by `architect` (author) and `documentation-writer` (upkeep).

## Inputs
The decision context, the options weighed, and the constraints (from the TSD, `CLAUDE.md`, requirements).

## Outputs
A numbered ADR in `architecture/adr/NNNN-title.md` (from `templates/adr.md`) and an updated index row in `architecture/adr/README.md`.

## Procedure
1. **Decide if it warrants an ADR.** Significant + reversible-cost-high + affects others → yes. Trivial/easily-reversed → no (a code comment suffices).
2. **Write Context neutrally** — the forces and constraints, no solution yet. Someone with no history should understand the problem.
3. **State the Decision** in active voice: "We will …".
4. **List Options** with honest pros/cons — including the one chosen and why the others lost.
5. **Spell out Consequences** — positive, negative/trade-offs, and follow-up work created.
6. **Assign a status** (Proposed → Accepted; later Superseded/Deprecated). Never edit an accepted ADR's decision — supersede it with a new one that links back.
7. **Update the index** (`architecture/adr/README.md`).

## Best practices
- One decision per ADR; number sequentially; never renumber.
- Immutable once Accepted — change via a superseding ADR, preserving history.
- Link ADRs to the TSD and to each other.
- Capture the trade-off, not just the winner — the rejected options are the value.

## Anti-patterns
- ADRs written after the fact with the reasoning invented. · Editing history instead of superseding. · Recording trivial decisions (noise). · Decision with no "options considered" (looks like there was no choice).
