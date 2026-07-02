#!/usr/bin/env bash
# PostToolUse(Edit|Write). Fires when a DB schema / migration file changes.
# Trigger: schema/migration file mutated. Action: remind + record; suggest database-engineer review.
# Non-blocking, but surfaces guidance so migrations don't ship unreviewed.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
path="$(event_field '.tool_input.file_path')"
[ -z "$path" ] && exit 0
is_schema_file "$path" || exit 0

log schema-change-guard "schema change: $path"
cat <<EOF
{"decision":"block","reason":"Schema/migration change detected in $path. Before continuing: (1) confirm the migration is reversible, (2) run it against a scratch DB, (3) have the database-engineer agent review for lock/downtime risk, (4) update architecture/ if the data model changed. Acknowledge these, then proceed."}
EOF
exit 0
