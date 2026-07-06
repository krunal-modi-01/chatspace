# Dependency vetting record: `uuid6`

- **Task:** T06 — UUIDv7 id generation utility (ADR-0005: message-id-scheme)
- **Package / version pinned:** `uuid6` `>=2024.7.10` (resolved: `2025.0.1`, per `backend/uv.lock`)
- **Reviewer & date:** `backend-engineer`, 2026-07-06
- **Outcome: GO**

## 0. Necessity
- [x] Needed: Python's stdlib `uuid` module does not implement UUIDv7 (RFC 9562) on the
      pinned runtime (3.12); a UUIDv7 generator is required by ADR-0005 for every table's
      app-generated, time-sortable primary key.
- [x] No existing dependency already provides this.
- [x] Footprint justified: single-purpose, ~14 KB sdist, pure Python, zero transitive deps.

## 1. License
- [x] SPDX id: **MIT** (confirmed via PyPI JSON metadata `info.license` and GitHub
      `license.spdx_id`).
- [x] Compatible with this project (no license file/policy restricting permissive deps).
- [x] Not copyleft.
- [x] Transitive licenses: none — `requires_dist` is empty (zero runtime dependencies).

## 2. Maintenance health
- [x] Last push: 2026-03-27 (recent, actively maintained).
- [x] 5 contributors on GitHub (`oittaa/uuid6-python`) — acceptable bus factor for a
      small, stable-scope library.
- [x] 7 open issues against 181 stars; repo not archived.
- [x] 17 published releases on PyPI; follows date-based versioning
      (`YYYY.MINOR.PATCH`), changelog visible via GitHub releases/tags.

## 3. Security & supply chain
- [x] SCA scan run: `uvx pip-audit` against the resolved backend dependency tree —
      **"No known vulnerabilities found."**
- [x] No unresolved CVEs.
- [x] No install-time scripts (pure Python wheel + sdist, no build/postinstall hooks).
- [x] No recent/unexpected maintainer change observed.
- [x] Package name checked against typosquatting — `uuid6` is the canonical package for
      the `oittaa/uuid6-python` project referenced by ADR-0005; not to be confused with
      the unrelated `uuid-utils` (Rust-backed) alternative also named in the ADR — we
      chose the pure-Python option to avoid a compiled-extension dependency at this
      project's scale.
- [x] Integrity hashes present in `backend/uv.lock` (`uv` records sdist/wheel hashes).

## 4. Transitive risk
- [x] Dependency tree: **zero runtime transitive dependencies** (`requires_dist: None`
      on PyPI) — minimal possible supply-chain surface.
- [x] No duplicate/conflicting versions in the resolved lockfile.

## 5. Version bump review
- N/A — first introduction of the dependency (added alongside the T03 async DB scaffold
  and consumed for the first time in this task).

## 6. Rollout
- [x] Exact version range pinned in `backend/pyproject.toml`
      (`uuid6>=2024.7.10`); exact resolved version + hash committed in `backend/uv.lock`.
- [x] Full backend test suite passes with the pinned version (`uv run pytest` — 71
      passed, including the new `tests/test_ids.py` property/monotonicity/concurrency
      suite for `app/core/ids.py`).
- [x] Not a risky/major bump — low blast radius, single call site
      (`app/core/ids.generate_id`), trivial to swap library later since it is wrapped
      behind one internal helper.
- [x] Rollback: revert `backend/uv.lock` + the `app/core/ids.py` addition; no data
      migration implication since ids are only ever consumed by not-yet-shipped table
      models.

## Known library limitation and mitigation
`uuid6.uuid7()` only forces its embedded millisecond timestamp to be non-decreasing
across calls in-process; the random tail bits are not guaranteed to keep the *full*
128-bit integer strictly increasing for two ids minted in the same millisecond. Since
ADR-0005 and the contract's WS ordering guarantee both depend on ids being reliably
time-sortable, `app/core/ids.generate_id()` wraps the library call with a process-local,
lock-protected monotonic counter that forces strict `id[i] < id[i+1]` ordering
regardless of the library's random tail. See `backend/app/core/ids.py` docstring and
`backend/tests/test_ids.py` for the property test.

## Decision
- **Outcome:** GO
- **Conditions / mitigations:** None beyond the strict-monotonicity wrapper documented
  above, which is implemented in `backend/app/core/ids.py`.
