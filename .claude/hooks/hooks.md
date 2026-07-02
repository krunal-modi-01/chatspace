# Hooks Catalog

Two classes of hooks ship in this pipeline:

1. **Claude Code hooks** — wired in `.claude/settings.json`, fired by the agent runtime during a session (`SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`). These shape and guard what Claude does *as it works*.
2. **Lifecycle hooks** — plain scripts wired into **git hooks and/or CI** (`pre-commit`, `on-test-fail`, `vuln-scan`, `pre-deploy`, `post-deploy`). These guard the *delivery pipeline* around Claude.

All hooks share `lib.sh` (logging, toolchain detection, event parsing) and are **stack-agnostic** — commands come from env vars in `settings.json` or are auto-detected from marker files (`package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`, `pom.xml`).

## Contract
- Read the JSON event from **stdin**. Exit `0` = allow/success. Exit `2` = **block** (stderr returned to Claude). Or print `{"decision":"block","reason":"…"}` to stdout for rich control.
- Hooks **must be fast** (<2s target) and **fail safe** — a crashing non-security hook should not wedge a session; a security hook should fail *closed*.
- Everything logs to `.claude/logs/hooks.log`.

## Claude Code hooks (settings.json)

| Hook | Event / Matcher | Trigger | Action | Failure handling | Notify | Blocking? |
|------|-----------------|---------|--------|------------------|--------|-----------|
| `session-start.sh` | `SessionStart` | Session begins | Inject recent decisions + git state as context | Non-fatal, logged | — | No |
| `pre-edit-guard.sh` | `PreToolUse: Edit\|Write\|MultiEdit` | Before file write | Block edits to secrets/generated/vendored paths | exit 2 blocks | — | **Yes** |
| `pre-bash-guard.sh` | `PreToolUse: Bash` | Before shell cmd | Block destructive commands (rm -rf /, force-push, mkfs…) | exit 2 blocks | — | **Yes** |
| `secret-scan.sh` | `PostToolUse: Edit\|Write` | After file write | gitleaks or regex scan for secrets | exit 2 blocks | — | **Yes (mandatory)** |
| `post-edit-format.sh` | `PostToolUse: Edit\|Write` | After file write | Format the single edited file | Non-fatal | — | No |
| `schema-change-guard.sh` | `PostToolUse: Edit\|Write` | Schema/migration file changed | Require reversibility + DB-engineer review checklist | Soft block (reason) | — | Advisory |
| `api-change-guard.sh` | `PostToolUse: Edit\|Write` | API contract changed | Require compat/version + api-reviewer checklist | Soft block (reason) | — | Advisory |
| `on-stop-verify.sh` | `Stop` | Turn ends w/ uncommitted code | Fast typecheck+lint; re-prompt if failing | Re-prompts once (loop-safe) | — | Advisory |

## Lifecycle hooks (git / CI)

| Hook | Trigger | Action | Failure handling | Notify | Blocking? |
|------|---------|--------|------------------|--------|-----------|
| `pre-commit.sh` | Before commit | Staged secret scan + lint + typecheck | exit 1 aborts commit | — | **Yes** |
| `on-test-fail.sh` | Test suite red | Capture output, emit pointer for bug-investigator | Reporter (never fails build) | `#ci` | No |
| `vuln-scan.sh` | Pre-merge / pre-deploy / dep change | SCA (osv/trivy/npm audit) + SAST (semgrep) | exit 1 on HIGH/CRITICAL | `#security` | **Yes (mandatory)** |
| `pre-deploy.sh` | Deploy initiated | Enforce approval + green tests + clean scan | exit 1 aborts deploy | `#releases` | **Yes** |
| `post-deploy.sh` | Deploy finished | Healthcheck, tag, seed 30m monitoring watch | exit 1 = rollback signal | `#releases`/`#oncall` | Advisory |

## Additional lifecycle points (implement per org)
`post-commit`, `pre-pr` (attach checklist + auto-summary), `post-pr` (assign reviewers), `pre-merge` (require green + approvals), `post-merge` (kick deploy pipeline). Templates for the PR/merge points live in `automation/` (CI) rather than as local scripts, since they belong to the platform, not the workstation.

## Enterprise enforcement
Security hooks (`secret-scan`, `vuln-scan`, `pre-commit`, `pre-bash-guard`) should be delivered via **Claude Code enterprise managed settings** so individuals cannot disable them. See `docs/12-best-practices.md`.
