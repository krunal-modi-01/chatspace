# Playbook: Incident Response

> How we respond when production is degraded or down. The priority order is **mitigate →
> communicate → fix → learn**. We stop the bleeding before we understand it fully; the durable
> fix and postmortem come after service is restored.

## When to use
- A production outage, severe degradation, data-integrity issue, or active security event.
- Any customer-facing impact that cannot wait for the normal `bug-fix.md` cadence.
- If unsure of severity, declare an incident anyway — under-reacting is the expensive mistake.

## Severity (SEV) triage
| SEV | Meaning | Example | Response |
|-----|---------|---------|----------|
| **SEV1** | Critical — full outage / data loss / active breach | Payments down, DB corruption | All-hands, page on-call immediately, exec comms |
| **SEV2** | Major — key feature broken, no workaround | Login failing for a region | Page on-call, dedicated IC |
| **SEV3** | Minor — degraded, workaround exists | Elevated latency within SLA budget | Business-hours response |

## Roles (assign at declaration, one person each)
- **Incident Commander (IC)** — owns the response, makes the calls, is *not* hands-on-keyboard.
- **Comms Lead** — owns status updates to stakeholders/customers; shields responders from noise.
- **Ops/Fixer(s)** — hands-on investigation and mitigation (`bug-investigator`, relevant engineer).
- **Scribe** — timestamps every action in the incident channel (feeds the postmortem timeline).

## Preconditions
- On-call rotation and paging are configured; `monitoring` MCP and alerting are live.
- An incident channel/bridge can be opened quickly.

## Steps

| # | Stage | Role / Agent | Skill | Hooks | MCP | Output |
|---|-------|--------------|-------|-------|-----|--------|
| 1 | Detect & declare; assign roles; open channel | IC | — | — | `monitoring`, `issue-tracker` | incident declared, SEV set, roles named |
| 2 | Assess blast radius | Ops / `bug-investigator` | `observability`, `debugging` | — | `monitoring`, `git` | scope + suspected trigger |
| 3 | **Mitigate first** — restore service by the fastest safe means | Ops / `devops-engineer` | `observability` | `post-deploy` | `cloud`, `kubernetes`, `monitoring` | service restored (rollback / flag off / traffic shed / scale up) |
| 4 | Communicate status on a cadence | Comms Lead | `documentation` | — | `issue-tracker`, `knowledge-base` | stakeholder updates every N min |
| 5 | Confirm recovery | IC + Ops | `observability` | — | `monitoring` | SLOs back to baseline |
| 6 | Stand down; hand off to durable fix | IC | — | — | `issue-tracker` | incident closed; follow-up ticket opened |
| 7 | Durable fix | `bug-investigator` → engineer | `debugging`, `testing` | full `bug-fix.md` / `hotfix.md` gates | — | root-cause fix shipped |
| 8 | **Blameless postmortem** (required for SEV1/2) | `bug-investigator` + `documentation-writer` | `documentation` | — | `knowledge-base` | `templates/postmortem.md` completed |

### Mitigate-before-fix
The fastest safe mitigation almost always beats a "proper" fix under fire:
- **Roll back** to the last known-good release (see `release.md` rollback).
- **Flip the feature flag** off for the offending capability.
- **Shed load / rate-limit / circuit-break** a failing dependency.
- **Scale up** if it is capacity, not correctness.
Only after service is restored do you move to the durable fix (Step 7) via the normal gates —
which are **not** skipped just because an incident preceded them.

## Human 🔒 gates
- **Declaration & severity** are human decisions (the IC).
- **Mitigation actions** with production blast radius (rollback, flag flips) are executed by a
  human with IC authorization; the deploy path still honours `pre-deploy`/`post-deploy`.
- **Postmortem sign-off** is a human gate before the incident is truly closed.

## Exit criteria
- Service restored to SLO and confirmed stable via `monitoring`.
- Root cause understood; durable fix shipped or scheduled with an owner and date.
- Postmortem completed (SEV1/2) and its action items filed as tickets.
- Timeline and decisions recorded in `knowledge/decisions.md`.

## Rollback
- Rollback *is* the primary mitigation here (Step 3). If a mitigation makes things worse, revert
  the mitigation and try the next option — the IC decides.
- Never attempt a speculative forward-fix under fire when a rollback is available.
