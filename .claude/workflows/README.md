# Workflows

**Playbooks** (in `playbooks/`) are for humans. **Workflows** here are for *machines*: declarative specs describing how agents are orchestrated — fan-out, gates, and hand-offs — so a run is deterministic and repeatable.

Two ways to run them:
1. **Interactively** — the main Claude Code session reads the spec and delegates to subagents in order.
2. **Programmatically** — as a Claude Code *Workflow script* (see `feature-flow.workflow.js`) that pipelines/parallelizes agents with barriers and verification. Use this for CI or large fan-outs.

## Design rules
- **Pipeline by default.** Independent items flow through stages without waiting for the whole batch.
- **Barriers only when needed** — e.g. dedup all review findings before verification.
- **Human 🔒 gates are hard stops** — a workflow pauses and surfaces for approval; it never auto-merges or auto-deploys.
- **Verify adversarially.** Findings from review/security get an independent verification pass before they're acted on.

## Specs
| Spec | Purpose |
|------|---------|
| `feature-flow.md` + `feature-flow.workflow.js` | idea → production for a feature |
| `bugfix-flow.md` | reproduce → fix → ship for a defect |
