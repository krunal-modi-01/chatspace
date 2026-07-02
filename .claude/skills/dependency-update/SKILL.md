---
name: dependency-update
description: Invoke when adding a new dependency or updating an existing one — vetting license, maintenance health, transitive risk, running SCA/vuln scans, reviewing the changelog, and staging the rollout.
---
# Dependency Update Skill
## Purpose
Vet every new or updated dependency before it enters the build so the project doesn't inherit legal, security, or maintenance risk.
## When invoked
- Any engineer adding a library or bumping a version in a manifest/lockfile.
- `security-reviewer` auditing dependency changes in a PR.
- Reacting to a vuln-scan alert or a Dependabot/Renovate PR.

## Inputs
- The package name, current version, and target version.
- The manifest/lockfile and the SCA tooling available.
- The dependency's repo, changelog, and license.

## Outputs
- A go/no-go recommendation with the vetting evidence.
- SCA/vuln scan results and any transitive concerns.
- A staged rollout / rollback note for risky bumps.
- Full checklist in `references/dependency-vetting-checklist.md`.

## Procedure
1. **Justify the dependency.** Confirm it's actually needed and not trivially replaceable by the standard library or an existing dep. Every dependency is a permanent liability (supply-chain, maintenance, size). Fewer is better.
2. **Check the license.** Verify it's compatible with the project's license and distribution model. Flag copyleft (GPL/AGPL) in proprietary products and any non-OSI/custom license for legal review. Check transitive licenses too, not just the direct one.
3. **Assess maintenance health.** Look at release cadence, last commit, open-vs-closed issues, number of maintainers (bus factor), and download/adoption signals. An unmaintained or single-maintainer package is a risk regardless of features.
4. **Evaluate transitive risk.** Inspect the dependency tree it drags in — count, depth, and any known-bad or unmaintained transitives. A small direct dep with a huge transitive footprint is a big dep.
5. **Run SCA / vulnerability scan.** Run the ecosystem scanner (`npm audit`, `pip-audit`, `osv-scanner`, Snyk, Trivy, etc.) against the resolved tree. Block on known criticals/highs without a fix path. Verify the lockfile is updated and integrity hashes are present.
6. **Review the changelog / diff for updates.** For a version bump, read the changelog and release notes for breaking changes, deprecations, and behavioral shifts. For a major bump, treat it as a `migration`. Be alert to suspicious changes (new maintainer, added network/postinstall scripts) — a supply-chain red flag.
7. **Pin and stage the rollout.** Pin the exact version and commit the lockfile. For risky/major updates, roll out through staging with the test suite and canary before prod, and keep the rollback (revert the lockfile) ready.

## Best practices
- Commit lockfiles; reproducible builds depend on them.
- Automate SCA in CI so every dependency change is scanned on the PR.
- Prefer well-maintained, widely-adopted libraries over clever niche ones.
- Batch routine patch/minor bumps; review majors individually.
- Re-vet on every bump — a trusted package can change ownership or behavior.

## Anti-patterns
- Adding a dependency for a one-liner you could write or already have.
- Ignoring or auto-merging Dependabot PRs without reading the diff.
- Accepting a copyleft/unknown license into a proprietary product without review.
- Floating/unpinned version ranges in production builds.
- Merging past a critical CVE with no fix path or documented mitigation.
- Judging a package by its direct code while ignoring its transitive tree.

## Files included
- `SKILL.md` — this file.
- `references/dependency-vetting-checklist.md` — per-dependency vetting checklist.
