#!/usr/bin/env bash
# on-test-fail lifecycle hook (call from CI test step, or from the test wrapper).
# Trigger: test suite exits non-zero. Action: capture failing output, hand to bug-investigator context,
# notify the channel. Failure handling: this hook itself never fails the build (it's a reporter).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
report="${1:-$LOG_DIR/last-test-output.txt}"
log on-test-fail "tests failed; report=$report"
"$DIR/notify.sh" "#ci" "🔴 Tests failed on $(git branch --show-current 2>/dev/null). Triage: run the bug-investigator agent with the failing output."
# Emit a machine-readable pointer the bug-investigator agent can pick up.
printf '{"event":"test_fail","report":"%s","branch":"%s"}\n' "$report" "$(git branch --show-current 2>/dev/null)"
exit 0
