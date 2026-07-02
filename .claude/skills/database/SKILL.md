---
name: database
description: Data modeling and datastore engineering — normalization vs deliberate denormalization, indexing strategy, query optimization (reading plans, killing N+1), safe zero-downtime migrations (expand/contract), and transactions/isolation levels. Use when designing a schema, adding or changing tables/columns/indexes, writing or diagnosing slow queries, planning a migration, or reasoning about consistency and locking. Used by the database-engineer agent. Stack-agnostic — detect the engine (Postgres/MySQL/SQLite/Mongo/etc.).
---
# Database Skill

## Purpose
Design data models and access patterns that stay correct and fast as data grows: schemas normalized by default and denormalized only with a measured reason, indexes that match real query patterns, migrations that ship without downtime or data loss, and transactions at the right isolation for the invariant being protected.

## When invoked
- The **database-engineer** agent uses this when designing a schema, adding/altering tables/columns/indexes, optimizing a slow query, or planning a schema change.
- Triggered by: "design the schema for…", "this query is slow", "add a column/index/table", "how do we migrate without downtime?", "we're seeing deadlocks / lost updates / dirty reads".
- Pairs with `backend` (transaction scoping, concurrency), `api-design` (shapes it serves), and `architecture` (which context owns which data).

## Inputs
- The domain entities, their relationships, and cardinalities.
- Access patterns: the top read and write queries by frequency and latency sensitivity (this drives indexing far more than the schema does).
- Data volume today and projected growth; consistency requirements; retention/compliance rules.
- The engine and its capabilities (transactional? indexing options? online DDL support?).

## Procedure
1. **Model from access patterns, not just entities.** List the handful of queries that will run most often and most latency-sensitively. The schema and indexes exist to serve those. In a document store, model around how data is read together; in a relational store, model the relationships and let indexes serve the reads.
2. **Normalize by default (to 3NF).** One fact in one place removes update anomalies and is the correct starting point. Use foreign keys and the right types; enforce invariants with constraints (`NOT NULL`, `UNIQUE`, `CHECK`, FK) — the database is your last line of integrity defense, not the app.
3. **Denormalize only with a measured reason.** Duplicate data (computed columns, cached aggregates, read models) when a proven read pattern can't meet its latency budget otherwise. When you do, own the consistency: who updates the copy, when, and how it's reconciled. Undisciplined denormalization is how data drifts.
4. **Index to match queries.** Add indexes for columns in `WHERE`, `JOIN`, `ORDER BY`, and frequent lookups. Prefer **composite indexes** ordered by selectivity and query shape (leftmost-prefix rule). Use **covering indexes** to serve reads from the index alone. Add **partial/filtered indexes** for hot subsets. Index foreign keys used in joins/deletes.
5. **Don't over-index.** Every index is write amplification and storage. Drop unused indexes (check usage stats). Watch for redundant indexes (one a prefix of another). Beware low-cardinality single-column indexes — often useless.
6. **Optimize queries by reading the plan.** Get the execution plan (`EXPLAIN ANALYZE` / equivalent). Look for full scans on large tables, missing index usage, bad row estimates (stale statistics), and expensive sorts/hash joins. Fix the cause: add/adjust an index, rewrite the predicate to be sargable (no functions wrapping indexed columns), reduce fetched columns/rows, or fix statistics.
7. **Eliminate N+1 access.** The most common backend perf bug: a query per row in a loop. Batch with a join, an `IN (...)`/`ANY`, or a dataloader. Detect it by counting queries per request in tests/logs.
8. **Scope transactions tightly and pick the right isolation.** Keep transactions short; never do external I/O inside them. Default to Read Committed for most work; use Repeatable Read / Serializable when you must prevent lost updates or phantom-based invariant violations — and be ready to retry on serialization failures. Prefer **optimistic concurrency** (version column) for low-contention updates and **`SELECT ... FOR UPDATE`** for short hot critical sections. Acquire locks in a consistent order to avoid deadlocks.
9. **Migrate with expand/contract (zero-downtime).** Never do a breaking DDL change in one step against a running system. Instead:
   - **Expand:** add the new column/table/index in a backward-compatible way (nullable/defaulted, created concurrently to avoid long locks). Deploy code that writes to both old and new.
   - **Migrate:** backfill existing data in batches (bounded, throttled) so you don't lock the table or blow up replication lag.
   - **Contract:** switch reads to the new shape, verify, then drop the old column/constraint in a later release.
   Each step is independently deployable and reversible. Add NOT NULL/constraints only after backfill, validated in a separate step.
10. **Make migrations safe and reversible.** Test on production-like data volume; know the lock behavior of each DDL statement on your engine; create indexes concurrently/online; time long backfills off-peak; and have a rollback (or forward-fix) plan. Keep migrations in version control, ordered, and idempotent where possible.
11. **Verify and instrument.** Confirm the query now uses the index and meets its latency budget on realistic data. Add slow-query logging and monitor index usage, table bloat, and replication lag.

## Best practices
- Let access patterns drive indexes; validate every index against a real query and a plan.
- Constraints in the database, not just the app — they're the integrity backstop across all writers.
- Composite index order = equality columns first, then range/sort; exploit the leftmost prefix.
- Backfill in bounded batches; create indexes concurrently; never a bare `ALTER` that rewrites/locks a big table at peak.
- Keep transactions short and I/O-free; choose isolation by the invariant, and handle serialization retries.
- Migrations are code: reviewed, versioned, tested on real volume, reversible.

## Anti-patterns
- **N+1 queries** — a lookup per row instead of a batched join/IN.
- **`SELECT *` and fetching more rows/columns than needed** — defeats covering indexes, wastes I/O.
- **Non-sargable predicates** — wrapping an indexed column in a function or leading-wildcard `LIKE '%x'`.
- **Index-everything or index-nothing** — write amplification vs full scans; both from not looking at plans.
- **Breaking migrations in one shot** — adding NOT NULL with default on a huge table, renaming a column clients still use, dropping before the contract phase.
- **Unbatched backfills** that lock tables or spike replication lag.
- **Long transactions holding locks** (especially across network calls) → deadlocks and timeouts.
- **Denormalization with no owner** — cached/duplicated data that nothing keeps in sync.
