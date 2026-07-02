#!/usr/bin/env bash
# Stop hook. When Claude finishes a turn, run a fast verification if code changed this session.
# Trigger: end of a response. Action: run typecheck+lint (fast) and, if failing, ask Claude to keep going.
# This closes the "claimed done but it doesn't compile" gap. Uses stop_hook_active to avoid loops.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event

# Avoid infinite loops: if we already triggered a continuation, let it stop.
if printf '%s' "$HOOK_EVENT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then exit 0; fi

ROOT="${CLAUDE_PROJECT_DIR:-.}"
# Only verify if there are uncommitted code changes.
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse >/dev/null 2>&1; then
  [ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ] && exit 0
fi

tc="$(resolve_cmd typecheck)"; ln="$(resolve_cmd lint)"
fail=""
if [ -n "$tc" ] && [ "$tc" != ":" ]; then eval "$tc" >/dev/null 2>&1 || fail+="typecheck "; fi
if [ -n "$ln" ] && [ "$ln" != ":" ]; then eval "$ln" >/dev/null 2>&1 || fail+="lint "; fi

if [ -n "$fail" ]; then
  log on-stop-verify "FAIL: $fail"
  printf '{"decision":"block","reason":"Verification failed (%s). Fix these before finishing, then stop."}' "$(echo "$fail" | sed 's/ $//')"
  exit 0
fi
log on-stop-verify "pass"
exit 0
