---
name: prompt-engineering
description: Invoke when authoring, editing, or reviewing this pipeline's agent definitions, skills, or prompts — role clarity, context minimalism, output contracts, evaluating/testing prompts, and versioning/changelog discipline.
---
# Prompt Engineering Skill
## Purpose
Author and maintain the agent prompts and skills that drive this SDLC pipeline so they are unambiguous, minimal, testable, and versioned — treated as production artifacts, not throwaway text.
## When invoked
- Anyone creating or editing an agent definition, a SKILL.md, or a system/task prompt in this repo.
- Reviewing a prompt change in a PR before it ships to the pipeline.

## Inputs
- The role the prompt serves and where it sits in the pipeline (which agent, what phase).
- The task's inputs, the expected output format, and its consumers (a human, or another agent).
- The existing prompt/skill and its version history.

## Outputs
- A prompt/skill with a clear role, minimal context, and an explicit output contract.
- Test cases / evals demonstrating it behaves as specified.
- A version bump and changelog entry.

## Procedure
1. **State the role and scope in one clear frame.** Open with who the agent is, what it owns, and — just as important — what it does NOT do. Ambiguous scope is the top cause of agents overreaching or under-delivering. Reference the canonical pipeline agent names (e.g. `code-reviewer`, `qa-engineer`) so responsibilities compose cleanly.
2. **Practice context minimalism.** Include only what the task needs to succeed; every extra instruction dilutes attention and invites contradiction. Push reusable procedure into a skill and reference it, rather than duplicating it inline. Prefer linking a skill over pasting its content.
3. **Define an explicit output contract.** Specify the exact shape the output must take (format, sections, schema, length) and who consumes it. If another agent consumes it, the contract is an interface — make it machine-parseable and stable. State what a "done" response looks like.
4. **Make instructions positive and concrete.** Say what to do, then note key anti-patterns. Prefer numbered procedures over vague prose. Give a worked example for anything non-obvious; examples steer behavior more reliably than adjectives.
5. **Write evals and test the prompt.** Before shipping, run the prompt against representative inputs — including edge cases and adversarial ones — and check the output meets the contract. Keep a small suite of input→expected-behavior cases so regressions are caught when the prompt changes. Treat "it worked once" as untested.
6. **Version and changelog every change.** Bump a version identifier in the prompt/skill and record what changed and why. Prompts drift silently; a changelog is how you bisect a behavior regression to the edit that caused it. Review prompt changes in PRs like code.
7. **Keep skills single-purpose and discoverable.** One skill = one capability with a precise `description` (its auto-invocation trigger). Follow the repo's SKILL.md template so agents can find and load it. If a skill is doing two jobs, split it.

## Best practices
- Role clarity first: who am I, what do I own, what's out of scope.
- Less context, better results — trim ruthlessly and link skills instead of inlining.
- Output contract is an API; keep it explicit and stable for downstream agents.
- Test prompts against edge cases before shipping; keep the evals.
- Version and changelog; review prompt edits as rigorously as code.
- Prefer concrete examples and numbered steps over abstract description.

## Anti-patterns
- Vague or overlapping roles that let agents drift out of scope.
- Kitchen-sink prompts stuffed with context "just in case."
- Implicit output format the consumer has to guess or parse ad hoc.
- Duplicating a skill's procedure inline instead of referencing it.
- Shipping a prompt change untested and unversioned.
- Negative-only instructions ("don't do X") with no positive guidance on what to do.

## Files included
- `SKILL.md` — this file.
