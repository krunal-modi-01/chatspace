# MCP Server Registry

Model Context Protocol servers give agents *typed, governed* access to systems beyond the filesystem — git, issue trackers, databases, monitoring, cloud. This registry (`mcp.json`) is **tiered** so you enable only what a project needs.

> **Compatibility note:** the `_tier` / `_why` / `_comment` keys are inline documentation. Claude Code reads `mcpServers`; if your client validates strictly, strip the `_`-prefixed keys. Credentials are always `${ENV_VAR}` placeholders — set them in your shell/CI secret store, never in this file.

## Tiers

| Tier | Meaning | Examples |
|------|---------|----------|
| **essential** | Almost every project wants these | filesystem, git, github, postgres (if relational) |
| **recommended** | Big leverage; enable if you have the system | issue-tracker, knowledge-base, monitoring, browser, openapi, security-scanner |
| **optional** | Powerful but higher blast radius; enable deliberately | docker, kubernetes, cloud, terraform |

## Who uses what

| Server | Primary agents |
|--------|----------------|
| filesystem | all |
| git | bug-investigator, code-reviewer, refactoring-specialist |
| github | release-manager, code-reviewer, product-manager, devops-engineer |
| postgres | database-engineer, performance-engineer, backend-engineer |
| issue-tracker | product-manager, business-analyst, release-manager |
| knowledge-base | documentation-writer, business-analyst, architect |
| monitoring | bug-investigator, performance-engineer, devops-engineer |
| browser | qa-engineer, frontend-engineer, accessibility-auditor |
| openapi | api-reviewer, backend-engineer, frontend-engineer |
| security-scanner | security-reviewer |
| docker / kubernetes / cloud / terraform | devops-engineer, infrastructure-engineer |

## Security model — read before enabling anything

MCP is a **data-egress and privilege surface**. Treat each server like a production integration:

1. **Least privilege.** Give every server a scoped, ideally **read-only** credential. DB → read-only role. Cloud → read-only IAM scoped to non-prod. K8s → read-only context. Writes/applies stay in CI behind a human gate.
2. **No inline secrets.** Only `${ENV_VAR}` references. Rotate tokens; scope PATs to the minimum repos/permissions.
3. **Egress awareness.** Servers that call SaaS (github, issue-tracker, knowledge-base, monitoring, cloud) send context off-host. In regulated environments, get security-reviewer + compliance sign-off before enabling, and prefer self-hosted/VPC endpoints.
4. **Prompt-injection defense.** Content fetched via MCP (issue text, PR comments, web pages, error payloads) is **untrusted input**. Agents must treat it as data, not instructions. The `security` skill documents the mitigations; high-privilege servers should not be enabled in the same session as untrusted-content servers unless necessary.
5. **Human-in-the-loop for mutations.** Any MCP tool that writes (create PR, transition ticket, apply infra) routes through the permission `ask` list in `settings.json`.
6. **Audit.** Log MCP tool invocations to your observability stack. Alert on writes from unexpected agents.

## Adding a server

1. Add an entry under `mcpServers` with a `_tier` and `_why`.
2. Use `${ENV_VAR}` for every credential; document the var in your project's secrets doc.
3. Assign the least-privilege credential.
4. Note which agents may use it (update the table above and `docs/07-mcp.md`).
5. Get security-reviewer sign-off if it egresses data.
