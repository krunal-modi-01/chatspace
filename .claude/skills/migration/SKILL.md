---
name: migration
description: Invoke when planning or executing a migration — schema/data migrations (backfill, dual-write, expand-contract), framework/version upgrades, and zero-downtime cutovers — always with a rollback plan.
---
# Migration Skill
## Purpose
Execute schema, data, and version migrations without downtime or data loss by decomposing them into reversible, independently deployable steps.
## When invoked
- `database-engineer` planning a schema or large data migration.
- `backend-engineer` upgrading a framework/runtime/major dependency version or changing a data model.
- Any cutover that must not drop traffic or lose data.

## Inputs
- Current and target state (old schema/version → new).
- Data volume, traffic profile, and the availability requirement (can we take downtime?).
- Deployment/rollout mechanism and how many app versions run concurrently.

## Outputs
- A step-by-step, reversible migration plan.
- Backfill/verification scripts and a cutover sequence.
- A written, tested rollback plan for each step.

## Procedure
1. **Prefer expand-contract (parallel change) over big-bang.** Never change a schema and its readers/writers in one irreversible step. Split into phases so old and new code can coexist during rollout:
   - **Expand** — add the new column/table/field, nullable/optional and backward-compatible. Old code ignores it.
   - **Migrate** — dual-write (write both old and new), backfill historical data, then switch reads to the new path.
   - **Contract** — once nothing reads the old path, remove it. Each phase ships and can roll back independently.
2. **Make schema changes additive and backward-compatible first.** Adding nullable columns/tables is safe; renaming, dropping, or narrowing types is not — model those as add-new → migrate → drop-old across separate deploys. Avoid long-locking DDL on large tables (use online/concurrent index builds).
3. **Backfill safely in batches.** Backfill in bounded batches with throttling to avoid saturating the DB or replication lag. Make backfill idempotent and resumable. Verify counts/checksums between old and new before switching reads.
4. **Dual-write during transition.** While both paths exist, write to both and read from the old until the new is verified, then flip reads. Guard the flip behind a feature flag so it's instant to toggle back.
5. **For framework/version upgrades:** read the changelog and migration guide for breaking changes; upgrade one major version at a time; run the full test suite and any codemods; upgrade in a branch/staging first; watch for transitive dependency conflicts (pairs with `dependency-update`).
6. **Cut over with zero downtime** using a flag or weighted rollout: shift a small % of traffic to the new path, watch error/latency SLOs (see `observability`), then ramp. Never flip 100% instantly on an unproven path.
7. **Write and rehearse the rollback plan before starting.** Every step must be reversible: additive changes are trivially reversible; the flag flip is instant; only the final contract (drop) is one-way — do it last, after a bake period. Take a backup/snapshot before any destructive step.

## Best practices
- One reversible change per deploy; never couple schema and behavior changes irreversibly.
- Feature-flag the read/write switch so rollback is a toggle, not a redeploy.
- Backfill idempotently, in batches, with monitoring for replication lag.
- Verify data equivalence (counts, checksums, sampled rows) before switching reads.
- Keep old and new paths coexisting long enough to prove the new one under real load.

## Anti-patterns
- Big-bang migration that changes schema + code + data in one irreversible deploy.
- Renaming/dropping a column in the same release that stops using it.
- Unthrottled backfill that saturates the primary or blows out replication lag.
- Destructive DDL (drop/rename) before confirming nothing reads the old path.
- No rollback plan, or a rollback that was never tested.
- Cutting 100% of traffic to an unproven path at once.

## Files included
- `SKILL.md` — this file.
