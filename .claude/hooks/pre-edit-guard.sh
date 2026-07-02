#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit). Blocks edits to protected/off-limits paths.
# Trigger: before any file mutation. Action: block if path matches deny rules.
# Failure handling: exit 2 blocks the edit and returns the reason to Claude.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$DIR/lib.sh"
read_event
path="$(event_field '.tool_input.file_path')"
[ -z "$path" ] && exit 0

# Never allow edits to secret/credential files or generated/vendored trees.
case "$path" in
  *.env|*.env.*|*.pem|*.key|*id_rsa*|*/secrets/*|*/credentials*)
    log pre-edit-guard "BLOCKED secret-file edit: $path"
    echo "Refusing to edit a secrets/credentials file ($path). Secrets belong in env vars, not source." >&2
    exit 2;;
  */node_modules/*|*/vendor/*|*/dist/*|*/build/*|*/target/*|*.generated.*|*_pb2.py|*.pb.go)
    log pre-edit-guard "BLOCKED generated/vendored edit: $path"
    echo "Refusing to edit generated/vendored file ($path). Change the source that produces it." >&2
    exit 2;;
esac
log pre-edit-guard "allow edit: $path"
exit 0
