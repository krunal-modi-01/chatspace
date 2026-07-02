# Technical Specification (TSD) — <Feature Name>

> Owner: `architect` agent (+ human architecture 🔒 gate). Input: functional spec. Output consumed by: build agents.
> Status: Draft | Approved · ADRs: <links> · Traces to spec: <link>

## 1. Summary & approach
The chosen technical approach in a paragraph. Link the ADR(s) that justify key choices.

## 2. Architecture
Component/context diagram (C4). Show boundaries, responsibilities, data flow.

```
[Client] → [API Gateway] → [Service] → [DB]
                              ↓
                        [Queue] → [Worker]
```

## 3. Components & responsibilities
| Component | Responsibility | New/changed | Owner agent |
|-----------|----------------|-------------|-------------|

## 4. Data model
Entities, relationships, key fields. Link `templates/database-design.md` instance. Migration strategy (expand/contract, reversibility).

## 5. API contracts
Endpoints/messages, request/response, errors, versioning, idempotency. Link `templates/api-contract.md` instance.

## 6. Non-functional targets
| Attribute | Target |
|-----------|--------|
| Latency (p95) | |
| Throughput | |
| Availability | |
| RTO / RPO | |
| Cost envelope | |

## 7. Failure modes & resilience
For each dependency: what happens when it's slow/down? Timeouts, retries, circuit breakers, fallbacks, idempotency.

## 8. Security & privacy
Threat surface (link `templates/threat-model.md`), authZ model, data classification, secrets handling.

## 9. Observability
Key logs/metrics/traces, SLIs/SLOs, alerts.

## 10. Rollout & migration
Feature flags, phased rollout, backward-compat, rollback plan.

## 11. Alternatives considered
Summary of options and why rejected (details in ADRs).

## 12. Risks
| Risk | Likelihood | Impact | Mitigation | Owner |
|------|-----------|--------|------------|-------|

---
🔒 **Approval gate:** human architecture sign-off before implementation.
