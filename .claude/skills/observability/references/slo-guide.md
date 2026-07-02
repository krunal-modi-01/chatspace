# SLI / SLO / Error-Budget Guide

A practical cheat-sheet for defining service reliability targets and alerting on them.

## Definitions

| Term | Definition |
| --- | --- |
| SLI | Service Level *Indicator* — a measured ratio: `good events / valid events`. |
| SLO | Service Level *Objective* — the target for an SLI over a window (e.g. 99.9% / 28d). |
| Error budget | `100% − SLO`. The permitted failure. 99.9% → 0.1% budget. |
| SLA | Contractual, customer-facing commitment (with penalties). Set the SLO stricter than the SLA. |

## Step 1 — Pick SLIs that reflect user happiness

Good SLI categories for request-driven services:
- **Availability**: proportion of valid requests that succeed (non-5xx, not timed out).
- **Latency**: proportion of valid requests served faster than a threshold (e.g. < 300 ms).
- **Quality/correctness**: proportion of responses that are correct/complete.

For pipelines/data: freshness, coverage, correctness, throughput.

SLI as a ratio:
```
SLI = good_events / valid_events   (exclude health checks / internal traffic from "valid")
```

## Step 2 — Set the SLO

- Base it on what users actually need, not on 100%. 100% leaves no room to ship or fail safely.
- Common tiers: 99% (~7h/month down), 99.9% (~43m/month), 99.95% (~22m/month), 99.99% (~4m/month). Each extra nine is exponentially more expensive.
- Pick a rolling window (28 or 30 days is typical) so the budget continuously reflects recent reliability.

## Step 3 — Compute the error budget

| SLO (30d) | Allowed downtime/failure |
| --- | --- |
| 99%   | ~7.2 hours |
| 99.9% | ~43.2 minutes |
| 99.95% | ~21.6 minutes |
| 99.99% | ~4.3 minutes |

Budget policy: when the budget is healthy, ship features. When it's exhausted, freeze risky changes and prioritize reliability work.

## Step 4 — Burn-rate alerting

Burn rate = how fast you are consuming the error budget relative to "even" consumption (1x = you'd exactly exhaust it over the window).

Recommended multi-window, multi-burn-rate alerts (Google SRE pattern) for a 30-day SLO:

| Severity | Burn rate | Long window | Short window | Budget consumed |
| --- | --- | --- | --- | --- |
| Page (fast) | 14.4x | 1 hour | 5 min | ~2% in 1h |
| Page (mid) | 6x | 6 hours | 30 min | ~5% in 6h |
| Ticket (slow) | 1x | 3 days | 6 hours | ~10% in 3d |

The short window confirms the burn is still happening (prevents alerting on an already-resolved spike). Alert only when *both* windows exceed the threshold.

## Step 5 — Validate the SLO

- [ ] SLI is measured from the user's perspective (edge/client-side where possible).
- [ ] Health checks and synthetic traffic are excluded from the denominator.
- [ ] The window and budget are agreed with stakeholders.
- [ ] Burn-rate alerts page on fast burn, ticket on slow burn.
- [ ] Every SLO alert links to a runbook.
- [ ] There is a written policy for what happens when the budget is exhausted.
- [ ] SLO is reviewed quarterly and adjusted to reality.
