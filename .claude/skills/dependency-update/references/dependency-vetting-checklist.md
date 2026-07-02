# Dependency Vetting Checklist

Run through this before adding a new dependency or approving a version bump. Attach the results to the PR.

## 0. Necessity
- [ ] The dependency is genuinely needed (not replaceable by stdlib or an existing dep).
- [ ] No existing dependency already provides this capability.
- [ ] The size/footprint is justified by the value.

## 1. License
- [ ] License identified (SPDX id) and recorded.
- [ ] Compatible with the project's license and distribution model.
- [ ] Not copyleft (GPL/AGPL/LGPL) in a proprietary/distributed product — or explicitly cleared by legal.
- [ ] Transitive licenses scanned; no surprise copyleft/custom/unknown licenses.

## 2. Maintenance health
- [ ] Last release / last commit is recent (not abandoned).
- [ ] More than one active maintainer (acceptable bus factor).
- [ ] Open/closed issue and PR ratio looks healthy; security issues get responses.
- [ ] Adoption signal (downloads, dependents, stars) is meaningful.
- [ ] Has a changelog and follows semantic versioning.

## 3. Security & supply chain
- [ ] SCA/vuln scan run on the resolved tree (`npm audit` / `pip-audit` / `osv-scanner` / Snyk / Trivy).
- [ ] No unresolved critical/high CVEs (or documented, accepted mitigation).
- [ ] No suspicious install-time scripts (postinstall running network/shell).
- [ ] Package ownership/maintainer hasn't recently and unexpectedly changed.
- [ ] Package name checked for typosquatting against the intended one.
- [ ] Integrity hashes / provenance present in the lockfile.

## 4. Transitive risk
- [ ] Reviewed the dependency tree it introduces (count and depth).
- [ ] No known-bad or unmaintained transitive dependencies.
- [ ] No duplicate/conflicting versions of shared transitives.

## 5. Version bump review (updates only)
- [ ] Changelog / release notes read for breaking changes and deprecations.
- [ ] Major version bump treated as a migration (see the `migration` skill).
- [ ] Diff reviewed for unexpected behavioral or dependency changes.

## 6. Rollout
- [ ] Exact version pinned; lockfile updated and committed.
- [ ] Full test suite passes with the new version.
- [ ] Risky/major bumps staged (staging → canary → prod).
- [ ] Rollback path confirmed (revert lockfile) and quick.

## Decision
- Outcome: **GO / NO-GO / GO-WITH-CONDITIONS**
- Conditions / mitigations:
- Reviewer & date:
