---
name: observability
description: Invoke when instrumenting or reviewing observability — the three pillars (logs/metrics/traces), defining SLIs/SLOs/error budgets, applying RED/USE methods, building dashboards, and alerting on symptoms rather than causes.
---
# Observability Skill
## Purpose
Make systems observable so operators can answer "is it healthy, and if not why" from telemetry alone: coherent logs, metrics, and traces tied to SLOs, with alerts on user-visible symptoms.
## When invoked
- `devops-engineer` instrumenting a service or building dashboards/alerts.
- `performance-engineer` establishing SLIs/SLOs and diagnosing regressions.
- `bug-investigator` reconstructing an incident from telemetry.

## Inputs
- The service and its user-facing operations and dependencies.
- Existing telemetry stack (Prometheus/Grafana, OTel, Datadog, etc.).
- Reliability targets or business expectations for the service.

## Outputs
- Instrumentation plan across the three pillars.
- SLI/SLO definitions with error budgets (see `references/slo-guide.md`).
- Dashboards (RED/USE) and symptom-based alert rules.

## Procedure
1. **Instrument the three pillars, each for its job:**
   - **Metrics** — cheap, aggregatable, always-on; drive dashboards and alerts.
   - **Logs** — high-detail events for forensic drill-down (see the `logging` skill).
   - **Traces** — per-request spans across services to find *where* latency/errors originate.
   Correlate them with a shared trace ID so an alert → dashboard → trace → log path exists.
2. **Apply RED to request-driven services:** Rate (req/s), Errors (failed req/s), Duration (latency distribution — track p50/p95/p99, never just the mean).
3. **Apply USE to resources** (CPU, memory, disk, queues, connection pools): Utilization, Saturation, Errors. RED tells you the service is unhealthy; USE often tells you why.
4. **Define SLIs, then SLOs.** An SLI is a measured ratio of good events to total (e.g. proportion of requests <300ms and non-5xx). An SLO is the target over a window (e.g. 99.9% over 28 days). The complement is the **error budget** — the allowed failure. Full detail and worked examples in `references/slo-guide.md`.
5. **Alert on symptoms, not causes.** Page on SLO burn (users are affected): high error rate, latency breach, error-budget burn-rate. Do NOT page on causes (high CPU, a full disk) unless they *directly* predict imminent user impact — those belong on dashboards or as low-urgency tickets. Cause-based paging creates alert fatigue and misses novel failures.
6. **Use multi-window burn-rate alerts** for SLOs: a fast-burn alert (e.g. 2% budget in 1h) pages immediately; a slow-burn alert (e.g. 10% in 6h) warns. This balances fast detection against false pages.
7. **Build layered dashboards:** a top-level SLO/RED overview per service, then USE panels per resource, then drill-down to traces. Every alert should link to the dashboard that explains it.

## Best practices
- Track percentiles (p95/p99), not averages — averages hide the tail users feel.
- One trace ID threaded through logs, metrics exemplars, and spans.
- Every page must be actionable and map to a runbook; if it isn't, downgrade it.
- Instrument at boundaries (inbound handlers, outbound calls, DB queries) for consistent coverage.
- Review SLOs and alert noise periodically; delete alerts that never actioned anything.

## Anti-patterns
- Paging on causes (CPU, memory, disk) instead of user-visible symptoms.
- Dashboards full of averages that mask tail latency.
- Metrics/logs/traces with no shared correlation ID.
- Alerts with no runbook, or that fire constantly and get muted.
- SLOs set to 100% (leaves zero error budget and no room to ship).
- High-cardinality labels (user IDs, request IDs) on metrics, exploding storage.

## Files included
- `SKILL.md` — this file.
- `references/slo-guide.md` — SLI/SLO/error-budget definition guide and burn-rate cheat-sheet.
