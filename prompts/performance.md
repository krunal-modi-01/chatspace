# Performance Prompt — v1.0.0
**Agent:** `performance-engineer` · **Skills:** `performance`, `observability`, `database` · **Output:** measured findings + optimizations
**Use when:** a perf budget is at risk, a hot path is slow, or before scaling a critical feature.

**Variables:** `{{TARGET}}` `{{BUDGET}}` `{{WORKLOAD}}` `{{METRICS_SOURCE}}`

---

Analyze and improve the performance of {{TARGET}} against budget {{BUDGET}} under workload {{WORKLOAD}}.

1. **Measure first.** Get a baseline from {{METRICS_SOURCE}} (`monitoring` MCP) or a profiler/load test. Never optimize on a guess.
2. **Find the bottleneck:** profile CPU/allocation/IO; check DB (N+1, missing index, slow query via `postgres` MCP), locks, and serialization points. Locate the dominant cost (Amdahl — optimize what matters).
3. **Hypothesize → change → re-measure.** Keep changes behavior-preserving (coordinate with `refactoring-specialist`/tests).
4. Consider, in order of leverage: algorithmic fix → query/index → caching (with invalidation plan) → concurrency/batching → scaling hardware.
5. Confirm the change meets the **budget** and didn't regress correctness (run tests) or blow cost.
6. Record the before/after numbers and the technique for `knowledge/patterns.md`.

Measure-before-optimize is mandatory. Beware caches without invalidation and micro-optimizations that don't move the p95.
