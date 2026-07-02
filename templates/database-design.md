# Database Design — <Feature / Domain>

> Owner: `database-engineer`. Guarded by `schema-change-guard` hook. Reviewed with `architect`, `performance-engineer`.

## Data model
Entities and relationships (ERD or DBML).

```
User 1───* Account 1───* Transaction
```

## Tables / collections
| Name | Purpose | Key fields | PII? | Retention |
|------|---------|-----------|------|-----------|

## Field definitions
| Table.field | Type | Null? | Default | Constraints | Index? |
|-------------|------|-------|---------|-------------|--------|

## Indexing strategy
| Index | Columns | Type | Rationale (query it serves) |
|-------|---------|------|-----------------------------|

## Integrity & invariants
Constraints, foreign keys, unique constraints, and business invariants enforced in-DB (e.g., balance ≥ 0, double-entry sum = 0).

## Migration plan (expand → migrate → contract)
1. **Expand:** additive, backward-compatible schema change.
2. **Backfill:** migrate data (batched, resumable).
3. **Switch:** app reads/writes new shape.
4. **Contract:** remove old columns after bake time.

- **Reversibility:** down-migration provided and tested.
- **Locking/downtime:** expected lock behavior; online-migration technique if large.
- **Rollback:** how to revert safely at each step.

## Performance considerations
Expected row counts/growth, hot queries, partitioning/sharding needs, caching.

---
🔒 Migrations against shared/prod environments require human approval.
