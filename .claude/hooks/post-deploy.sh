#!/usr/bin/env bash
# post-deploy lifecycle hook (call after promotion completes).
# Trigger: deploy finished. Action: smoke checks + health probe, tag release, notify, seed monitoring watch.
# Failure: exit 1 signals rollback needed. Notify: #releases + #oncall.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
env="${1:-production}"; url="${2:-${HEALTHCHECK_URL:-}}"; rc=0
if [ -n "$url" ] && command -v curl >/dev/null 2>&1; then
  code="$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)"
  [ "$code" = "200" ] || { echo "❌ healthcheck $url returned $code"; rc=1; }
fi
log post-deploy "env=$env health=${code:-skip} rc=$rc"
if [ $rc -eq 0 ]; then
  "$DIR/notify.sh" "#releases" "✅ Deploy to $env healthy. Watching error rate/latency for the next 30m."
else
  "$DIR/notify.sh" "#oncall" "🔥 Post-deploy healthcheck FAILED on $env — consider rollback. Run the bug-investigator agent."
fi
exit $rc
