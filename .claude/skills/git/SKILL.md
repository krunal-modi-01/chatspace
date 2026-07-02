---
name: git
description: Version-control workflow — branching model, Conventional Commits, small focused PRs, rebase vs merge, finding regressions with bisect, safe revert/rollback, and protected-branch hygiene. Use when creating branches or commits, opening/structuring a PR, choosing rebase vs merge, hunting a regression, reverting a bad change, or setting branch protection. Used by all engineering agents and the release-manager. Stack-agnostic.
---
# Git Skill

## Purpose
Keep history legible, changes small and reversible, and the main branch always releasable. Good git practice is a safety mechanism: it makes regressions findable, changes revertible, and reviews fast.

## When invoked
- **All engineering agents** use this when branching, committing, or opening PRs; the **release-manager** uses it for release branches, tags, reverts, and rollbacks.
- Triggered by: "create a branch/commit", "open a PR", "rebase or merge?", "which commit broke this?", "revert/rollback the change", "set up branch protection", "the PR is too big".

## Inputs
- The change being made and its scope; the target branch and the repo's branching model.
- The repo's conventions: commit message style, PR template, protected-branch rules, CI gates.
- For regression hunting: a known-good and known-bad revision and a reproducing check.

## Outputs
- Well-scoped branches and atomic commits with Conventional Commit messages.
- Small, reviewable PRs with clear descriptions and green CI.
- A clean, bisectable main-branch history.
- Safe reverts/rollbacks and, where relevant, a bisect result identifying the offending commit.

## Procedure
1. **Branch off the integration branch.** Use short-lived feature branches from `main` (trunk-based) or the model the repo uses. Name them meaningfully (`feat/order-idempotency`, `fix/1234-null-cart`). Never commit directly to a protected branch. Rebase your branch on the latest `main` regularly to avoid big-bang merges.
2. **Make atomic commits.** Each commit is one logical, self-consistent change that builds and passes tests — not a snapshot of "end of day". This is what makes revert and bisect useful. Stage selectively (`git add -p`) to keep unrelated changes apart.
3. **Write Conventional Commit messages.** `type(scope): summary` in the imperative, ≤ ~72 chars, then a body explaining *why* (not what — the diff shows what), then footers. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `chore`. Mark breaking changes with `!` or a `BREAKING CHANGE:` footer. Reference issues in the footer. This drives changelogs and semver automation.
4. **Keep PRs small and single-purpose.** A reviewable PR does one thing and is small enough to review carefully (rule of thumb: a few hundred lines of meaningful change). Split large work into stacked/sequential PRs. Include what changed, why, how it was tested, and any risk/rollout notes. A big PR gets a rubber-stamp review, not a real one.
5. **Choose rebase vs merge deliberately.**
   - **Rebase** your *local, unpushed/unshared* feature branch onto `main` to keep a linear history and clean up WIP commits before review (`git rebase -i` to squash/reorder — not available interactively in all sandboxes, but the principle stands).
   - **Never rebase shared/public history** others have based work on — it rewrites commit ids and breaks their branches.
   - **Merge** (or squash-merge) to integrate the PR into `main`. Squash-merge for a tidy one-commit-per-PR history; merge-commit to preserve the branch's commits. Pick one policy per repo and hold it.
6. **Keep `main` green and releasable.** Every merge must have passing CI. Broken main blocks everyone — fix-forward or revert immediately.
7. **Find regressions with `git bisect`.** Given a good and a bad commit, `git bisect start`, mark `bad`/`good`, and let git binary-search the range. Automate with `git bisect run <test-script>` that exits 0 for good, non-zero for bad — it finds the offending commit in log₂(n) steps. Atomic, building commits are what make this reliable. `git bisect reset` when done.
8. **Revert safely.** To undo a change already on a shared branch, use `git revert <sha>` — it creates a new commit that inverts the change, preserving history (never rewrite shared history to "remove" a commit). For a merge commit, revert with `-m 1`. Revert is the rollback primitive: fast, reviewable, and traceable.
9. **Roll back a release** by reverting the offending commit(s) or re-deploying the last known-good tag — decided with the release-manager. Tag releases (annotated tags, semver) so rollback targets are unambiguous.
10. **Protect branches.** On `main`/release branches: require PRs, passing status checks, up-to-date-with-base, at least one review (code-reviewer / security-reviewer as policy dictates), and block force-push and direct push. Optionally require signed commits and linear history.

## Best practices
- Small branches, small PRs, atomic commits — the whole workflow gets easier downstream.
- Commit messages explain *why*; the diff already shows *what*.
- Rebase private history to clean up; merge to integrate; never rewrite shared history.
- Keep `main` always releasable; revert fast rather than debugging on a broken main.
- Let commits stay bisectable (each builds/tests green) so `git bisect` actually works.
- Tag releases with annotated semver tags for unambiguous rollback points.

## Anti-patterns
- **Giant, multi-purpose PRs** that mix refactor + feature + formatting — unreviewable, un-bisectable, un-revertable.
- **Rewriting shared history** (force-push to a branch others use) — breaks everyone's clones.
- **Vague commits** ("fix stuff", "wip", "changes") — useless changelog and history.
- **Committing directly to `main`** or force-pushing it.
- **`git reset --hard` to "undo" a pushed commit** instead of `git revert` — data loss and history divergence.
- **Merging red CI** or leaving main broken while you debug.
- **End-of-day snapshot commits** that don't build — bisect and revert become useless.
