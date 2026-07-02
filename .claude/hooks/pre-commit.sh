#!/usr/bin/env bash
# pre-commit lifecycle hook (wire via .git/hooks/pre-commit or pre-commit framework, and CI).
# Trigger: before a commit is created. Action: secret scan + lint + typecheck on staged files.
# Failure: exit 1 aborts the commit. Notification: none (local). Logging: hooks.log.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
rc=0
# 1) secrets
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks protect --staged -q 2>/dev/null || { echo "❌ secret detected in staged changes"; rc=1; }
fi
# 2) lint + typecheck (fast gates)
ln="$(resolve_cmd lint)"; tc="$(resolve_cmd typecheck)"
[ -n "$ln" ] && [ "$ln" != ":" ] && { eval "$ln" || { echo "❌ lint failed"; rc=1; }; }
[ -n "$tc" ] && [ "$tc" != ":" ] && { eval "$tc" || { echo "❌ typecheck failed"; rc=1; }; }
log pre-commit "rc=$rc"
[ $rc -ne 0 ] && echo "Commit blocked. Fix the above or use the bug-investigator/code-reviewer agent."
exit $rc
