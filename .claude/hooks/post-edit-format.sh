#!/usr/bin/env bash
# PostToolUse(Edit|Write|MultiEdit). Auto-formats the edited file so diffs stay clean.
# Trigger: after a file mutation. Action: run the project formatter on that one file.
# Failure handling: non-fatal (formatting failure never blocks work); logged for visibility.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
path="$(event_field '.tool_input.file_path')"
[ -z "$path" ] || [ ! -f "$path" ] && exit 0

fmt="$(resolve_cmd format)"
if [ -z "$fmt" ] || [ "$fmt" = ":" ]; then log post-edit-format "no formatter; skip $path"; exit 0; fi

# Only touch the single file where the tool supports it; else skip silently.
case "$path" in
  *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.md) command -v prettier >/dev/null 2>&1 && prettier --write "$path" >/dev/null 2>&1;;
  *.go)  command -v gofmt   >/dev/null 2>&1 && gofmt -w "$path" >/dev/null 2>&1;;
  *.py)  command -v ruff    >/dev/null 2>&1 && ruff format "$path" >/dev/null 2>&1;;
  *.rs)  command -v rustfmt >/dev/null 2>&1 && rustfmt "$path" >/dev/null 2>&1;;
  *) : ;;
esac
log post-edit-format "formatted (best-effort): $path"
exit 0
