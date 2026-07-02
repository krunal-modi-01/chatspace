#!/usr/bin/env bash
# notify.sh <channel> <message> — shared notification helper used by lifecycle hooks.
# Routes to Slack/Teams/etc. via a webhook URL in env; falls back to logging.
# Usage: notify.sh "#releases" "Deploy v1.2.3 started"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
channel="${1:-#eng}"; msg="${2:-}"
log notify "[$channel] $msg"
if [ -n "${CLAUDE_NOTIFY_WEBHOOK:-}" ] && command -v curl >/dev/null 2>&1; then
  curl -fsS -X POST -H 'Content-Type: application/json' \
    -d "$(printf '{"channel":"%s","text":"%s"}' "$channel" "$msg")" \
    "$CLAUDE_NOTIFY_WEBHOOK" >/dev/null 2>&1 || log notify "webhook delivery failed"
fi
exit 0
