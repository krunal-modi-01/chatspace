---
name: documentation
description: Invoke when writing or reviewing docs — READMEs, API references, runbooks, ADRs — choosing the right type for the audience, treating docs as code, keeping them from drifting, and adding diagrams.
---
# Documentation Skill
## Purpose
Produce documentation that its intended reader can actually use, kept in sync with the system through doc-as-code discipline.
## When invoked
- `documentation-writer` authoring or reviewing any doc artifact.
- Any change that adds a public API, a new service, an operational procedure, or a significant decision.

## Inputs
- Who the reader is and what they need to accomplish.
- The system/API/decision being documented and its source of truth (code, specs).
- Existing docs and their location/format conventions.

## Outputs
- The right doc type for the audience, written and placed in the repo.
- Diagrams where structure or flow needs them.
- Where applicable, generated-from-source API docs.

## Procedure
1. **Identify the audience and pick the doc type.** Each type answers a different question:

   | Type | Reader | Answers |
   | --- | --- | --- |
   | README | Newcomer/user | What is this, how do I run/use it? |
   | API reference | Integrator | What are the endpoints/params/errors? |
   | Runbook | On-call operator | It's on fire — what do I do, step by step? |
   | ADR | Future maintainer | What did we decide, and why? |
   | Tutorial/how-to | Task-doer | How do I accomplish X? |

   Don't mix them (a README is not a runbook).
2. **Write a README** that gets a newcomer productive: one-line what/why, quickstart (install → run → verify), key configuration, and links out to deeper docs. Front-load the fastest path to a working state.
3. **Write API reference from the source of truth.** Generate from the OpenAPI/GraphQL schema or code annotations where possible so it can't drift. Document each endpoint's purpose, params, auth, success + error responses, and a real example. Coordinate with the `api-reviewer` agent on the contract.
4. **Write runbooks as executable procedures.** Symptom → diagnosis steps → remediation steps → escalation/rollback. Concrete commands, expected output, and links to dashboards/alerts. An operator at 3am should not have to think.
5. **Write ADRs for consequential decisions.** Context → decision → alternatives considered → consequences (including downsides). Keep them immutable and dated; supersede rather than edit.
6. **Treat docs as code.** Docs live in the repo next to what they describe, are reviewed in the same PR as the change, and (where feasible) validated in CI (link-checkers, doc-tests, schema-drift checks). A change that alters behavior must update its docs in the same PR.
7. **Add diagrams for structure and flow** using diagram-as-code (Mermaid, PlantUML) so they version and diff. Use them for architecture, sequence/data flow, and state machines — not decoration. Keep one diagram to one idea.

## Best practices
- Write for the reader's goal, not the author's mental model.
- Keep the source of truth singular; generate docs from it when possible.
- Show a working example early; examples beat prose.
- Update docs in the same PR as the code — this is the single biggest anti-drift lever.
- Prune stale docs aggressively; wrong docs are worse than none.

## Anti-patterns
- Docs that duplicate code comments or restate the obvious.
- API docs hand-maintained separately from the schema (guaranteed drift).
- Runbooks that describe theory instead of exact steps/commands.
- ADRs edited in place, erasing the decision history.
- Screenshot/binary diagrams that can't diff or update.
- Merging a behavior change without touching its docs.

## Files included
- `SKILL.md` — this file.
