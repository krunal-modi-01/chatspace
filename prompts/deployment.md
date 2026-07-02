# Deployment Prompt — v1.0.0
**Agent:** `release-manager` (+ `devops-engineer`) · **Skills:** `git`, `docker`, `kubernetes`, `observability` · **Output:** `templates/release-notes.md` + a monitored rollout
**Use when:** preparing and shipping a release.

**Variables:** `{{VERSION}}` `{{CHANGES_SINCE_TAG}}` `{{ENV}}` `{{ROLLOUT_STRATEGY}}`

---

Prepare and ship {{VERSION}} to {{ENV}} using {{ROLLOUT_STRATEGY}}.

1. **Assemble release notes** from {{CHANGES_SINCE_TAG}} (Conventional Commits/PRs) into `templates/release-notes.md`. Call out breaking changes + migrations.
2. **Pre-flight gates (must all pass):** tests green · `vuln-scan` clean · migrations reversible & rehearsed · docs updated · required 🔒 human approval recorded (`DEPLOY_APPROVED_BY`). `pre-deploy.sh` enforces these.
3. **Roll out** per strategy (canary → phased → full). Never all-at-once for high-risk changes.
4. **Watch** (`observability`/`monitoring` MCP): error rate, latency (p95), saturation for a defined bake window. `post-deploy.sh` seeds the watch.
5. **Decision:** promote if healthy; **roll back** immediately on regression (have the exact rollback command ready).
6. Tag the release; record the outcome.

Deployment is irreversible-ish — treat the 🔒 approval and rollback plan as mandatory, not optional. Prod migrations need explicit human confirmation.
