---
name: architecture
description: System design — choosing architectural patterns (layered, hexagonal, event-driven, microservices vs monolith), defining service and module boundaries, C4 modeling, non-functional targets, and documenting trade-offs. Use when starting a new system or major feature, when a design decision spans multiple components, when defining boundaries/contracts between teams, or when non-functional requirements (scale, latency, availability) drive structure. Used by the architect agent. Stack-agnostic.
---
# Architecture Skill

## Purpose
Turn requirements and constraints into a defensible system structure — the smallest set of components, boundaries, and contracts that meets the functional and non-functional requirements while keeping change cheap. Every structural decision is justified by a trade-off, not a preference.

## When invoked
- The **architect** agent uses this when a feature or system is too large for a single service/module, when boundaries between teams or bounded contexts must be drawn, or when non-functional requirements (throughput, p99 latency, availability, RTO/RPO, cost) force a structural choice.
- Triggered by: "design the system for…", "should this be a service or a module?", "how do these components talk?", "will this scale to N?", greenfield kickoff, or a proposed change that crosses two or more existing components.
- Precedes implementation skills (`backend`, `frontend`, `database`, `api-design`) and typically produces work that `adr-authoring` records.

## Inputs
- Functional requirements / user stories (from product-manager, business-analyst).
- Non-functional targets: expected load, growth curve, latency budgets, availability SLO, data residency, compliance, cost ceiling.
- Existing system landscape: current services, data stores, integration points, team topology (who owns what).
- Constraints: team size and skills, deadline, budget, mandated platforms.

## Outputs
- A **C4 model** to the needed depth: System Context (always), Container diagram (usually), Component diagram (for the complex containers only). Code-level diagrams almost never.
- Named **boundaries**: modules/services/bounded contexts, what each owns, and the contract at each seam (sync API, async event, shared nothing).
- A **trade-off analysis**: the options considered, the deciding non-functional forces, and the rejected alternatives with reasons.
- **Non-functional budget allocation**: how the latency/availability/cost budget is split across components.
- Feed into `adr-authoring` for the decisions worth recording.

## Procedure
1. **Restate the drivers.** List the top 3-5 forces that will actually shape structure (e.g. "10x growth in 18 months", "p99 < 200ms", "team of 4", "must survive single-AZ loss"). If you can't name them, you're not ready to design — go back to inputs.
2. **Start with the boring option.** Assume a well-structured **modular monolith** with a single primary datastore until a driver proves it insufficient. Distribution is a cost you pay for a specific reason (independent scaling, independent deploy cadence, team autonomy, fault isolation, polyglot), not a default.
3. **Draw boundaries around change and ownership, not around nouns.** Group by what changes together and who owns it (bounded contexts / capabilities). A good boundary hides a decision; a bad one leaks it. Minimize the number of seams that a typical feature must cross.
4. **Pick a pattern per boundary** (see `references/patterns-cheatsheet.md`). Layered for CRUD-heavy apps; hexagonal/ports-and-adapters when the domain is rich and you must isolate it from I/O; event-driven when components must decouple in time or fan out; microservices only when independent deploy/scale/fault-isolation is a proven need. It is normal to mix (a hexagonal service inside an event-driven system).
5. **Define each contract explicitly.** For every seam decide: synchronous (request/response) vs asynchronous (event/message); the schema and its ownership; failure semantics (timeout, retry, idempotency); and consistency expectation (strong vs eventual). Write these down — they are the real interface.
6. **Model with C4.** Context first (system + external actors/systems). Then Containers (deployable/runnable units + data stores + protocols on the arrows). Component diagrams only for containers whose internals aren't obvious. Keep diagrams versioned as text (e.g. Mermaid/PlantUML) next to the code.
7. **Allocate the non-functional budget.** Push the latency/availability targets down onto components: if the end-to-end budget is 200ms and a call fans out to three services, each gets a slice plus network. If availability must be 99.9% and you have three serial dependencies, each needs materially better — do the arithmetic, don't hope.
8. **Attack the design.** For each critical driver ask: what's the failure mode, the bottleneck, the single point of failure, the data-loss window? Sketch the load path for the hottest request and the recovery path for the worst outage.
9. **Compare at least two options honestly.** Tabulate options against the drivers. Name what you're giving up. The winning option is the one whose downsides you can live with, stated explicitly.
10. **Record the decision.** Hand the significant, hard-to-reverse choices to `adr-authoring`. Cheap, reversible choices don't need an ADR — say so.

## Best practices
- Optimize for **reversibility**: make one-way-door decisions slowly and two-way-door decisions fast. Most decisions are two-way doors.
- Prefer **evolutionary architecture** — a modular monolith you can later carve into services beats a premature distributed system you must later merge.
- Make the **implicit explicit**: consistency model, ownership of each schema, failure behavior at each seam. Undocumented seams become incidents.
- Keep the C4 model **just deep enough**. Diagrams that go stale are worse than none; store them as text and review them in PRs.
- State assumptions and their expiry ("valid while writes < 5k/s"); design so the assumption is cheap to revisit.
- Design for **observability** from day one: every seam should be traceable, and every SLO must be measurable.

## Anti-patterns
- **Resume-driven / hype-driven design** — microservices, Kafka, or a new datastore because it's fashionable, not because a driver demands it.
- **Distributed monolith** — services that must be deployed together, share a database, or call each other synchronously in tight loops. You paid for distribution and got none of the benefits.
- **Big-design-up-front** with no feedback loop; or its opposite, no design at all until the seams have already calcified wrong.
- **Boundaries drawn around database tables or layers** instead of capabilities — leads to features that touch every service.
- **Ignoring the non-functional arithmetic** — assuming availability/latency compose for free across serial dependencies.
- **Diagrams as decoration** — pretty pictures with no protocols, no failure semantics, no ownership.

## Files included
- `references/patterns-cheatsheet.md` — when to use each architectural pattern, with a trade-offs table.
