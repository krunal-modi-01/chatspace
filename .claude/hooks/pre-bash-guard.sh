#!/usr/bin/env bash
# PreToolUse(Bash). Last-line defense against destructive shell commands.
# Trigger: before any Bash tool call. Action: block obviously destructive/irreversible ops.
# Note: settings.json permissions are the primary control; this catches composed commands.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
cmd="$(event_field '.tool_input.command')"
[ -z "$cmd" ] && exit 0

deny_patterns=(
  'rm[[:space:]]\+-rf[[:space:]]\+/'      # rm -rf /
  'git[[:space:]]\+push[[:space:]].*--force'
  'git[[:space:]]\+push[[:space:]].*-f\b'
  ':\(\)\{'                                # fork bomb
  'mkfs'
  'dd[[:space:]]\+if=.*of=/dev/'
  '>[[:space:]]*/dev/sd'
  'DROP[[:space:]]\+DATABASE'
)
for p in "${deny_patterns[@]}"; do
  if printf '%s' "$cmd" | grep -Eiq "$p"; then
    log pre-bash-guard "BLOCKED: $cmd"
    echo "Blocked a potentially destructive command matching /$p/. If intentional, a human must run it manually." >&2
    exit 2
  fi
done
exit 0
