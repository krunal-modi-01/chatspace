#!/usr/bin/env bash
# pre-deploy lifecycle hook (call from the deploy job before promotion).
# Trigger: deploy initiated. Action: enforce release gates (tests green, vuln-scan clean, approval present).
# Failure: exit 1 aborts deploy. Notify: #releases. Human gate: DEPLOY_APPROVED_BY must be set.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
env="${1:-production}"; rc=0
[ -z "${DEPLOY_APPROVED_BY:-}" ] && { echo "❌ no human approval (DEPLOY_APPROVED_BY unset)"; rc=1; }
"$DIR/vuln-scan.sh" >/dev/null 2>&1 || { echo "❌ vuln-scan gate failed"; rc=1; }
[ "${TESTS_GREEN:-false}" != "true" ] && { echo "❌ tests not confirmed green (TESTS_GREEN!=true)"; rc=1; }
log pre-deploy "env=$env approver=${DEPLOY_APPROVED_BY:-none} rc=$rc"
if [ $rc -eq 0 ]; then
  "$DIR/notify.sh" "#releases" "🚀 Deploying to $env (approved by ${DEPLOY_APPROVED_BY})."
else
  "$DIR/notify.sh" "#releases" "⛔ Deploy to $env BLOCKED by pre-deploy gate."
fi
exit $rc
