# Postmortem — <Incident Title>

> Owner: `bug-investigator` (facilitates) + on-call. **Blameless.** Output feeds `knowledge/decisions.md` and tech-debt backlog.

- **Incident ID / date:** · **Severity:** SEV1–4 · **Duration:** detect→resolve
- **Author:** · **Status:** Draft | Reviewed

## Summary
2–3 sentences: what happened, who/what was affected, how it was resolved.

## Impact
Users affected, requests failed, revenue/SLA impact, data integrity effects.

## Timeline (UTC)
| Time | Event |
|------|-------|
| T0 | Change deployed / trigger |
| T+? | First alert / detection |
| T+? | Mitigation started |
| T+? | Resolved |

## Root cause
The technical root cause (5-whys). Distinguish trigger vs underlying cause.

## Detection
How was it detected? How long to detect (MTTD)? Should it have been caught earlier (test/gate gap)?

## Resolution & recovery
What fixed it. MTTR. Was rollback used?

## What went well / what went poorly
Bullets.

## Action items (each with owner + due + ticket)
| Action | Type (prevent/detect/mitigate) | Owner | Due | Ticket |
|--------|--------------------------------|-------|-----|--------|

## Lessons → pipeline
Which gate/hook/test would have prevented this? Propose the change (new hook, test, ADR).
