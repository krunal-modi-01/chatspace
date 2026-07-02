---
name: terraform
description: Invoke when authoring or reviewing Terraform/HCL — module structure, remote state and locking, plan-before-apply discipline, drift detection, workspaces/environments, and keeping secrets out of state. `apply` is always human-gated.
---
# Terraform Skill
## Purpose
Manage infrastructure as code safely and reproducibly: well-structured modules, protected remote state, and a strict plan-review-before-apply workflow where the actual apply is gated on a human.
## When invoked
- `infrastructure-engineer` writing, refactoring, or reviewing Terraform for any environment.
- Reviewing an IaC change before it reaches an environment (pairs with the `aws`/`kubernetes` skills for the target).
- Investigating drift between declared and real infrastructure.

## Inputs
- The change to make or module to author, and the target environment (dev/staging/prod).
- Backend/state configuration and workspace layout.
- Provider versions and any org module registry.

## Outputs
- HCL for modules/root configs following the structure below.
- A `terraform plan` output summarized for human review (adds/changes/destroys, with destroys called out).
- Drift report and remediation proposal.
- Never an unattended `apply`.

## Procedure
1. **Structure modules for reuse.** A module is a directory with `main.tf`, `variables.tf`, `outputs.tf`, and `versions.tf`. Root configs compose modules; keep root thin. One responsibility per module (e.g. `network`, `db`, `service`). Pin module and provider versions.
2. **Configure remote state with locking.** Use a remote backend (S3 + DynamoDB lock table, Terraform Cloud, or equivalent). Never commit `terraform.tfstate`. Enable state locking so concurrent applies cannot corrupt state. Enable versioning on the state bucket for recovery.
3. **Separate environments** by state, not by copy-paste. Prefer separate backend keys/workspaces per env with a shared module and per-env `*.tfvars`. Workspaces are fine for identical-shape envs; use separate root dirs when envs diverge structurally.
4. **Always plan before apply.**
   - `terraform init` (verify backend/providers), then `terraform validate` and `terraform fmt -check`.
   - `terraform plan -out=tfplan` and read the summary. **Scrutinize every destroy/replace** — a replace on a stateful resource can mean data loss.
   - Present the plan for human approval. **Do not run `terraform apply` autonomously.** Apply is human-gated; hand off the reviewed `tfplan`.
5. **Keep secrets out of state.** Never hardcode credentials in HCL. Source secrets from a secrets manager (AWS Secrets Manager, Vault) via data sources at runtime, or inject via CI env. Remember that resource attributes and outputs *are stored in state* — treat state as sensitive, encrypt it, and restrict access.
6. **Detect and reconcile drift.** Periodically `terraform plan` (or `terraform plan -refresh-only`) against real infra. If drift is found, decide: adopt reality into code, or re-apply to restore declared state. Never edit resources by hand in a Terraform-managed environment except in a break-glass incident, then reconcile immediately.
7. **Review checklist** for any change: no plaintext secrets; no `0.0.0.0/0` unless justified; destroys understood; provider/module versions pinned; `for_each` over `count` where identity matters; sensitive outputs marked `sensitive = true`.

## Best practices
- `terraform fmt` and `validate` in CI; block un-formatted or invalid HCL.
- Pin provider versions with `~>`; use a lockfile (`.terraform.lock.hcl`) committed to the repo.
- Prefer `for_each` (stable identity) over `count` (index churn causes needless replacements).
- Small, reviewable plans; one logical change per PR.
- Store the reviewed plan artifact and apply exactly that plan, so what is reviewed is what ships.

## Anti-patterns
- Running `apply` without a reviewed plan, or automating apply to prod without a human gate.
- Committing state files or hardcoding secrets in HCL.
- Manual console changes to Terraform-managed resources ("clickops" drift).
- One giant monolithic root module with no boundaries.
- Using `count` for named resources so a mid-list removal reindexes and destroys the wrong ones.
- Ignoring destroy/replace lines in the plan on stateful resources.

## Files included
- `SKILL.md` — this file.
