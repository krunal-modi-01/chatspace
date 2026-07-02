#!/usr/bin/env bash
# PostToolUse(Edit|Write). Fires when an API contract (OpenAPI/proto/GraphQL/route) changes.
# Trigger: API file mutated. Action: flag for api-reviewer + versioning/compat check. Non-blocking.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
path="$(event_field '.tool_input.file_path')"
[ -z "$path" ] && exit 0
is_api_file "$path" || exit 0

log api-change-guard "api change: $path"
cat <<EOF
{"decision":"block","reason":"API contract change detected in $path. Before continuing: (1) is this backward-compatible? if not, bump the API version, (2) update the OpenAPI/proto spec and regenerate clients, (3) have the api-reviewer agent check naming/status-codes/pagination, (4) update consumer docs. Acknowledge, then proceed."}
EOF
exit 0
