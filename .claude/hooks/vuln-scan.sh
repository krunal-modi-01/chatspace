#!/usr/bin/env bash
# vuln-scan lifecycle hook (call in CI pre-merge, and pre-deploy). MANDATORY security gate.
# Trigger: pre-merge / pre-deploy, or on dependency change. Action: SCA + SAST.
# Failure: exit 1 on HIGH/CRITICAL findings -> blocks merge/deploy. Notify: #security.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
rc=0; findings=""
# Dependency vulnerabilities (SCA) — try common scanners in order.
if   command -v osv-scanner >/dev/null 2>&1; then osv-scanner scan . 2>/dev/null | grep -qiE 'HIGH|CRITICAL' && { findings+="deps "; rc=1; }
elif command -v trivy       >/dev/null 2>&1; then trivy fs --severity HIGH,CRITICAL --exit-code 1 . >/dev/null 2>&1 || { findings+="deps "; rc=1; }
elif command -v npm         >/dev/null 2>&1 && [ -f package.json ]; then npm audit --audit-level=high >/dev/null 2>&1 || { findings+="npm-audit "; rc=1; }
fi
# Static analysis (SAST).
if command -v semgrep >/dev/null 2>&1; then
  semgrep --error --severity ERROR --config auto . >/dev/null 2>&1 || { findings+="sast "; rc=1; }
fi
log vuln-scan "rc=$rc findings=[$findings]"
if [ $rc -ne 0 ]; then
  "$DIR/notify.sh" "#security" "🚨 vuln-scan found HIGH/CRITICAL issues: $findings — blocked. Run the security-reviewer agent."
  echo "❌ vuln-scan failed: $findings. Remediate or get security-reviewer sign-off."
fi
exit $rc
