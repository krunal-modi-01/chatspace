#!/usr/bin/env bash
# lib.sh — shared helpers for all pipeline hooks.
# Stack-agnostic: commands come from env (set in settings.json / settings.local.json)
# or are auto-detected from project marker files. Source this from every hook.
#
# Hooks receive a JSON event on stdin and can:
#   - exit 0            -> allow / success (stdout shown to user in transcript)
#   - exit 2            -> BLOCK the action; stderr is fed back to Claude
#   - print JSON to stdout with {"decision":"block","reason":"..."} for rich control
# See docs/06-hooks.md for the contract.

set -uo pipefail

LOG_DIR="${CLAUDE_HOOK_LOG_DIR:-${CLAUDE_PROJECT_DIR:-.}/.claude/logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || true

log() { # log <hook-name> <message>
  printf '%s [%s] %s\n' "$(date -u +%FT%TZ 2>/dev/null || echo now)" "$1" "$2" >> "$LOG_DIR/hooks.log" 2>/dev/null || true
}

# Read the raw JSON event from stdin once, cache it.
read_event() { HOOK_EVENT="$(cat)"; export HOOK_EVENT; }

# Extract a field from the event JSON without requiring jq (best-effort).
event_field() { # event_field <key>
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$HOOK_EVENT" | jq -r "$1 // empty" 2>/dev/null
  else
    # crude fallback for flat string fields like .tool_input.file_path
    local key="${1##*.}"
    printf '%s' "$HOOK_EVENT" | grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/'
  fi
}

# Resolve a project command from env, else detect from marker files. Echoes "" if unknown.
resolve_cmd() { # resolve_cmd test|lint|format|typecheck
  local kind="$1" envvar
  case "$kind" in
    test)      envvar="${CLAUDE_TEST_CMD:-}";;
    lint)      envvar="${CLAUDE_LINT_CMD:-}";;
    format)    envvar="${CLAUDE_FORMAT_CMD:-}";;
    typecheck) envvar="${CLAUDE_TYPECHECK_CMD:-}";;
  esac
  if [ -n "$envvar" ]; then printf '%s' "$envvar"; return; fi

  local root="${CLAUDE_PROJECT_DIR:-.}"
  if   [ -f "$root/package.json" ]; then
    case "$kind" in
      test) printf 'npm test --silent';; lint) printf 'npm run lint --silent';;
      format) printf 'npm run format --silent';; typecheck) printf 'npm run typecheck --silent';;
    esac
  elif [ -f "$root/go.mod" ]; then
    case "$kind" in test) printf 'go test ./...';; lint) printf 'go vet ./...';; format) printf 'gofmt -l .';; typecheck) printf 'go build ./...';; esac
  elif [ -f "$root/Cargo.toml" ]; then
    case "$kind" in test) printf 'cargo test';; lint) printf 'cargo clippy';; format) printf 'cargo fmt --check';; typecheck) printf 'cargo check';; esac
  elif [ -f "$root/pyproject.toml" ] || [ -f "$root/setup.py" ]; then
    case "$kind" in test) printf 'pytest -q';; lint) printf 'ruff check .';; format) printf 'ruff format --check .';; typecheck) printf 'mypy .';; esac
  elif [ -f "$root/pom.xml" ]; then
    case "$kind" in test) printf 'mvn -q test';; lint) printf 'mvn -q verify';; format) printf ':';; typecheck) printf 'mvn -q compile';; esac
  else
    printf ''   # unknown toolchain -> caller degrades gracefully
  fi
}

# True if a path looks like it changed an API contract.
is_api_file() { case "$1" in *openapi*|*swagger*|*.proto|*schema.graphql|*/routes/*|*/controllers/*|*/api/*) return 0;; *) return 1;; esac; }
# True if a path looks like a DB schema / migration.
is_schema_file() { case "$1" in *migration*|*migrations/*|*schema.sql|*schema.prisma|*/models/*|*.dbml) return 0;; *) return 1;; esac; }
