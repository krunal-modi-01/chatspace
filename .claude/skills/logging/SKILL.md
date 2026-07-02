---
name: logging
description: Invoke when adding, reviewing, or standardizing application logging — structured/JSON logs, log levels, correlation/trace IDs, what must NEVER be logged (secrets/PII), sampling, and log hygiene.
---
# Logging Skill
## Purpose
Produce logs that are useful for debugging and safe to store: structured, correctly leveled, correlatable across services, and free of secrets and PII.
## When invoked
- `backend-engineer` adding logging to a service or reviewing log statements in a PR.
- `devops-engineer` standardizing log format/ingestion or tuning volume/cost.
- Any change that touches auth, payments, or personal data (log-safety review).

## Inputs
- The code path being instrumented and its failure modes.
- Existing logging library/format and the aggregation backend (ELK, Loki, CloudWatch, etc.).
- Data-sensitivity classification of the values in scope (PII, secrets, tokens).

## Outputs
- Structured log statements at correct levels with a correlation/trace ID.
- A redaction/deny-list for sensitive fields.
- Sampling/retention recommendations where volume matters.

## Procedure
1. **Emit structured logs**, not string concatenation. One JSON object per event with stable field names: `timestamp`, `level`, `message`, `service`, `trace_id`, plus event-specific fields. Structured logs are queryable; free-text is not.
2. **Use levels deliberately:**

   | Level | Use for | Example |
   | --- | --- | --- |
   | ERROR | Failed operation needing attention | unhandled exception, failed payment |
   | WARN | Recovered/degraded, may need attention | retry succeeded, fallback used |
   | INFO | Business-significant events | order placed, user logged in |
   | DEBUG | Developer diagnostics, off in prod | branch taken, intermediate value |

   Do not log routine success at ERROR/WARN; do not hide failures at DEBUG.
3. **Propagate correlation/trace IDs.** Generate or accept a `trace_id` at the edge (from the incoming header or a new UUID), attach it to the logging context, and include it in every log line and outbound request header. This is what lets you reconstruct one request across services.
4. **Redact before logging — this is non-negotiable.** NEVER log: passwords, tokens, API keys, secrets, full card numbers/CVV, auth headers, session cookies, or unmasked PII (SSN, full email lists, health data). Prefer allow-listing fields to log over blindly dumping objects. Add redaction at the logger layer (a serializer/filter) so it can't be forgotten at call sites.
5. **Log the right context on errors:** what operation, key identifiers (IDs, not raw PII), and the error/stack — not the request body wholesale. Enough to reproduce, nothing sensitive.
6. **Sample high-volume paths.** For hot paths, sample DEBUG/INFO (e.g. 1-in-N) or use head/tail sampling for traces so cost and noise stay bounded while errors are always kept.
7. **Maintain hygiene:** consistent field names across services, bounded message size, no logging inside tight loops, no PII in log-derived metrics/labels, and a defined retention policy.

## Best practices
- Configure log level per environment (DEBUG in dev, INFO in prod) via config, not code.
- Centralize the logger; wrap it so redaction and trace-ID injection are automatic.
- Log identifiers, not payloads. A user ID is fine; the user's record is not.
- Make errors actionable: include enough to locate the cause without a debugger.
- Keep timestamps in UTC/ISO-8601 and let the backend localize.

## Anti-patterns
- Logging secrets, tokens, auth headers, or PII — even at DEBUG.
- `log.error()` for expected/handled conditions (alert fatigue).
- Unstructured string logs that can't be queried or parsed.
- Dumping whole request/response bodies or ORM objects.
- No trace/correlation ID, so multi-service debugging is guesswork.
- Unbounded logging in hot loops driving cost and hiding signal.

## Files included
- `SKILL.md` — this file.
