---
name: performance
description: Invoke when investigating or improving performance — setting perf budgets, measuring before optimizing, profiling, diagnosing common bottlenecks (N+1 queries, allocation, IO), load testing, and designing a caching strategy.
---
# Performance Skill
## Purpose
Improve latency, throughput, and resource efficiency through measurement-driven optimization: profile to find the real bottleneck, fix it, and prove the gain against a budget.
## When invoked
- `performance-engineer` diagnosing a regression, running load tests, or setting perf budgets.
- Any request to "make X faster" or explain a latency/throughput/cost problem.

## Inputs
- The operation and its current vs target latency/throughput/resource numbers.
- A reproducible workload or representative traffic.
- Access to profilers, load-test tooling, and telemetry (pairs with `observability`).

## Outputs
- A profile identifying the dominant cost, with numbers before and after.
- The specific fix and its measured impact.
- Perf budget and load-test results where relevant.

## Procedure
1. **Set a budget and define the metric first.** Decide what "fast enough" means (e.g. p95 < 200ms at 500 rps, memory < 512MB) before touching code. Without a target you can't know when to stop.
2. **Measure before optimizing — always.** Reproduce the problem and capture a baseline. Intuition about hotspots is usually wrong. Never optimize code you haven't profiled.
3. **Profile to find the dominant cost.** Use the right tool: CPU profiler (flame graph) for compute, allocation profiler for GC pressure, query logs/`EXPLAIN` for DB, distributed traces for cross-service latency. Find the biggest contributor — Amdahl's law: optimizing a 5% cost caps you at 5% gain.
4. **Diagnose against the common bottleneck catalogue:**

   | Symptom | Likely cause | Fix direction |
   | --- | --- | --- |
   | Latency scales with result count | N+1 queries | batch / eager-load / join |
   | High GC / memory churn | excess allocation in hot path | reuse buffers, avoid boxing, stream |
   | CPU near idle but slow | blocking IO / serial awaits | parallelize, async, connection pooling |
   | Slow under load only | lock contention / pool exhaustion | reduce critical section, size pools |
   | Repeated identical work | no caching | cache with correct invalidation |

5. **Fix the dominant cost, then re-measure.** Change one thing, re-run the same benchmark, confirm the gain, and check you didn't regress correctness or another metric. Stop when the budget is met — don't gold-plate.
6. **Design caching deliberately.** Cache only when reads dominate and staleness is tolerable. Decide layer (client/CDN/app/DB), key, TTL, and — hardest — invalidation. Measure hit rate. A cache with a low hit rate or wrong invalidation is worse than none.
7. **Load test for scale claims.** Use a load tool (k6, Locust, JMeter) with realistic traffic shape to find the knee where latency degrades and to validate the budget at target concurrency. Test steady state and spikes; watch USE metrics for the saturating resource.

## Best practices
- Benchmark in a prod-like environment; dev-box numbers mislead.
- Report percentiles (p95/p99), not averages.
- Change one variable per measurement so cause and effect are clear.
- Prefer algorithmic/architectural wins (fewer queries, better data structure) over micro-optimizations.
- Keep the benchmark as a regression guard in CI for critical paths.

## Anti-patterns
- Optimizing without profiling ("this looks slow").
- Micro-optimizing a path that isn't the bottleneck.
- Caching without an invalidation strategy → stale data bugs.
- Reporting mean latency and hiding the tail.
- Load testing with unrealistic (all-cache-hit, single-key) traffic.
- Trading correctness or readability for unmeasured speed.

## Files included
- `SKILL.md` — this file.
