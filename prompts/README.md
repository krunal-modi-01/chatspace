# Prompt Library

Reusable, **parameterized** prompt templates — the standardized way to invoke pipeline work so quality doesn't depend on who's typing. They complement agents (which carry standing instructions); a prompt is the *task-specific request* you hand an agent.

## Conventions
- **Placeholders:** `{{UPPER_SNAKE}}` — fill before use.
- **Versioning:** each prompt has a semver header. Breaking wording changes bump the version; log in this README's changelog. Owned by the platform/DevEx team; edits go through the `prompt-engineering` skill checklist.
- **Composability:** prompts reference `templates/` for output shape and name the owning agent + skills.
- **Output contract:** every prompt states the expected output format so results are consistent and machine-checkable.

## Index
| Prompt | Agent | Use when |
|--------|-------|----------|
| `planning.md` | product-manager / business-analyst | turn an idea into scoped requirements |
| `architecture.md` | architect | design the technical approach |
| `implementation.md` | backend/frontend/mobile-engineer | build a scoped task |
| `bugfix.md` | bug-investigator | diagnose + fix a defect |
| `review.md` | code-reviewer | review a diff |
| `testing.md` | qa-engineer | generate/assess tests |
| `refactoring.md` | refactoring-specialist | improve code safely |
| `deployment.md` | devops/release-manager | prepare + ship a release |
| `security.md` | security-reviewer | threat model + secure review |
| `performance.md` | performance-engineer | find + fix perf issues |
| `documentation.md` | documentation-writer | produce/update docs |

## Changelog
- v1.0.0 — initial library.
