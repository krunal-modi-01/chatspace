---
name: refactoring
description: Behavior-preserving code improvement under test cover — reducing duplication, untangling coupling, renaming for clarity, extracting abstractions, and paying down tech debt. Use when improving structure without changing behavior, or when code smells impede a change. Never mixes functional changes with restructuring. Used by the refactoring-specialist agent. Stack-agnostic.
---

# Refactoring Skill

## Purpose
Improve the internal structure of code without changing its observable behavior, in small safe steps that keep the suite green throughout.

## When invoked
Preparing messy code for a change, paying down prioritized tech debt, or acting on code-review simplification findings. Primary skill of `refactoring-specialist`.

## Inputs
The target code, its test coverage, and the goal/smell to address.

## Outputs
A behavior-preserving diff (tests unchanged in intent and still green), ideally split into small reviewable commits.

## Code smell catalog (triggers)
| Smell | Refactoring |
|-------|-------------|
| Duplicated logic | Extract function/module; reuse existing utility |
| Long function/class | Extract; split responsibilities |
| Feature envy / high coupling | Move behavior to the data; introduce boundary |
| Primitive obsession | Introduce value object/type |
| Shotgun surgery | Consolidate the scattered concern |
| Dead code | Delete (verify with coverage/usage) |

## Procedure
1. **Safety net first.** Confirm tests cover current behavior. If thin, add **characterization tests** *before* touching anything.
2. **Small steps.** One transformation at a time; run tests after each. Commit frequently.
3. **Structure only.** No behavior change mixed in. If you spot a bug, note it for `bug-investigator` — do not fix it here.
4. **Large refactors → strangler-fig.** Stand up the new path beside the old, migrate callers incrementally, delete the old once nothing references it.
5. **Preserve contracts.** No public API/schema change (or route through `api-reviewer` if intended).
6. Verify full suite green; hand to `code-reviewer`.

## Best practices
- Never refactor and change behavior in the same commit — it makes review and rollback impossible.
- Keep diffs small; several PRs beat one giant one.
- Let tests define "behavior preserved"; if you can't tell, add a test.

## Anti-patterns
- "Big bang" rewrite without tests. · Refactoring on a red suite. · Sneaking a bug fix or feature into a refactor. · Renaming across the codebase in an unreviewable mega-diff.
