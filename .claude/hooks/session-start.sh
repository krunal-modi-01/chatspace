#!/usr/bin/env bash
# SessionStart hook. Injects durable project context so every session starts oriented.
# Trigger: session begins. Failure: non-fatal (never blocks a session). Logs: hooks.log.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
log session-start "session started (pipeline ${PIPELINE_VERSION:-?})"

ROOT="${CLAUDE_PROJECT_DIR:-.}"
ctx=""
[ -f "$ROOT/knowledge/decisions.md" ] && ctx+=$'\n## Recent decisions\n'"$(tail -n 20 "$ROOT/knowledge/decisions.md" 2>/dev/null)"
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse >/dev/null 2>&1; then
  ctx+=$'\n## Git\nbranch: '"$(git -C "$ROOT" branch --show-current 2>/dev/null)"
  ctx+=$'\nuncommitted files: '"$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
fi

# additionalContext is surfaced to the model at session start.
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":%s}}' \
  "$(printf '%s' "$ctx" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '""')"
exit 0
