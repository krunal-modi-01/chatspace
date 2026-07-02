#!/usr/bin/env bash
# PostToolUse(Edit|Write|MultiEdit). Scans the just-written file for leaked secrets.
# Trigger: after a file mutation. Action: block (exit 2) if a high-signal secret pattern appears.
# This gate is MANDATORY and must not be removed. Failure -> edit is reported back for immediate fix.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
path="$(event_field '.tool_input.file_path')"
[ -z "$path" ] || [ ! -f "$path" ] && exit 0

# Prefer a real scanner if present; else fall back to regex heuristics.
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks detect --no-git --source "$path" -q 2>/dev/null; then
    log secret-scan "BLOCKED gitleaks hit: $path"
    echo "gitleaks detected a secret in $path. Remove it and use an env var / secret manager." >&2
    exit 2
  fi
  exit 0
fi

patterns=(
  'AKIA[0-9A-Z]{16}'                         # AWS access key
  'ASIA[0-9A-Z]{16}'
  '-----BEGIN[A-Z ]*PRIVATE KEY-----'
  'ghp_[A-Za-z0-9]{36}'                      # GitHub PAT
  'xox[baprs]-[A-Za-z0-9-]+'                 # Slack token
  'sk-[A-Za-z0-9]{20,}'                      # generic API secret / OpenAI-style
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'  # JWT
  '(password|passwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*["'\''][^"'\'' ]{8,}'
)
for p in "${patterns[@]}"; do
  if grep -Eiq "$p" "$path"; then
    log secret-scan "BLOCKED pattern /$p/: $path"
    echo "Possible secret in $path (matched /$p/). Remove it; use env vars or a secret manager. If false positive, add an allowlist comment and re-run." >&2
    exit 2
  fi
done
log secret-scan "clean: $path"
exit 0
