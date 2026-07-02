# Playbook: Migration (data / framework / infrastructure)

> Move a system from one state to another — a schema change, a framework upgrade, a data model
> reshape, or an infrastructure swap — **without downtime and without a point of no return**.
> The governing pattern is **expand-contract**, and every step must be reversible until the
> final contract.

## When to use
- A change that cannot be deployed atomically: schema migrations on a live DB, a data reshape/
  backfill, splitting or merging services, swapping a datastore or framework version.
- Anything where old and new code/data must coexist during the transition.
- Small, reversible schema tweaks may just use `feature-development.md` with the
  `database-engineer` — reserve this playbook for changes big enough to need a cutover plan.

## Preconditions
- A `technical-spec` and, for data changes, a `database-design` (`templates/database-design.md`).
- An ADR recording the migration approach and its reversibility (`templates/adr.md`).
- Backups/snapshots verified and restorable. A feature flag mechanism is available for cutover.
- Rough data volume and backfill time estimated (dictates batching and windows).

## The expand-contract pattern
1. **Expand** — add the new shape (column/table/service/API) *additively*. Nothing reads it yet;
   the old shape still works. Fully backward-compatible, trivially reversible.
2. **Migrate** — **dual-write** to old and new, then **backfill** existing data into the new shape
   in idempotent batches. Reads still come from the old shape.
3. **Cutover** — behind a **feature flag**, switch reads to the new shape for a small cohort, then
   widen. Old shape still populated (safety net).
4. **Contract** — once the new shape is proven over a soak period, stop writing the old shape and
   remove it. This is the **only irreversible step** — gate it behind human approval and a soak.

## Steps

| # | Stage | Agent | Skill | Hooks | MCP | Output |
|---|-------|-------|-------|-------|-----|--------|
| 1 | Design migration & reversibility plan | `architect` + `database-engineer` | `migration`, `database`, `adr-authoring` | `schema-change-guard` | `postgres`, `knowledge-base` | spec + ADR + rollback plan |
| 2 | **Expand**: additive schema/shape change | `database-engineer` / `backend-engineer` | `database`, `migration` | `schema-change-guard`, `pre-edit-guard` | `postgres`, `git` | new shape deployed, unused |
| 3 | **Dual-write**: write both old & new | `backend-engineer` | `backend` | `secret-scan`, `post-edit-format` | `filesystem`, `git` | writes hit both shapes |
| 4 | **Backfill** existing data (idempotent, batched, resumable) | `database-engineer` | `database`, `migration` | — | `postgres`, `monitoring` | new shape fully populated & reconciled |
| 5 | Verify parity (old vs new) | `qa-engineer` | `testing` | `on-test-fail` | `postgres`, `monitoring` | parity checks green |
| 6 | **Cutover** reads behind a feature flag, cohort by cohort | `backend-engineer` + `devops-engineer` | `backend`, `observability` | `pre-deploy` 🔒, `post-deploy` | `cloud`, `monitoring` | reads served from new shape |
| 7 | Soak & monitor | `devops-engineer` + `performance-engineer` | `observability`, `performance` | `post-deploy` | `monitoring` | stable over the soak window |
| 8 | 🔒 **Approval to contract (irreversible)** | *human maintainer* | — | `pre-deploy` | `github` | go/no-go to remove old shape |
| 9 | **Contract**: stop dual-write; remove old shape | `database-engineer` | `database`, `migration` | `schema-change-guard`, `pre-deploy` 🔒 | `postgres`, `git` | old shape retired |
| 10 | Record & close | `documentation-writer` | `documentation` | — | `knowledge-base` | ADR marked Accepted; note in `knowledge/decisions.md` |

### Reversibility rules
- Steps 2–7 are **fully reversible**: flip the flag back, keep reading the old shape, stop the
  backfill. Old data is intact because you never stopped writing it.
- Step 9 (contract) is the **only** irreversible action. It requires the Step-8 human gate **and**
  a completed soak. Take a fresh, verified backup immediately before it.
- `schema-change-guard` fires on any schema-touching edit and requires a paired, reversible
  migration + a rollback path — it blocks destructive changes that lack one.

## Human 🔒 gates
1. **Step 6 — cutover deploy** via `pre-deploy` (`DEPLOY_APPROVED_BY`).
2. **Step 8 — contract approval.** A human explicitly authorizes the irreversible removal after
   the soak. This is the single most important gate in the playbook.

## Exit criteria
- New shape serves 100% of reads; parity checks were green through the soak.
- Old shape removed (or, if deliberately retained, that decision is recorded).
- Backups verified before the contract step; migration + rollback scripts committed.
- ADR marked Accepted; outcome logged in `knowledge/decisions.md`.

## Rollback
- **Before Step 9 (contract):** flip the feature flag to read the old shape, stop the backfill,
  keep dual-writing. No data loss — this is the whole point of expand-contract.
- **After Step 9:** rollback means restoring from the pre-contract backup and re-expanding — treat
  as an incident (`incident-response.md`). This is why Step 8 is a hard human gate.
- Record every rollback and its cause in `knowledge/decisions.md`.
