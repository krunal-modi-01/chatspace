"""Redaction guard: keeps secrets, tokens, message content, and PII out of logs.

The deny-list below is derived directly from the frozen database design
(`docs/spec/chatspace-v1-database-design.md`) and the technical spec §8/§9:

- **Secrets** (never logged, never returned) — `hashed_password`, refresh /
  invite / reset tokens and their hashes, JWT signing material, access/
  refresh token values, the `sid` session-id claim, generic `password`/
  `authorization` fields.
- **Message content** (F68/R24) — `messages.content` and any field carrying
  a raw chat message body.
- **PII** (R24/R44/R47) — `username`, `email`, `first_name`, `last_name`,
  `avatar_url`, `last_seen`, `recipient_id` (DM participant identity),
  `attachments.filename`, `sessions.ip_address`, `sessions.user_agent`,
  `invites.email`.

Safe-to-log identifiers (UUIDv7 primary keys, `channel_id`, `message_id`,
`sender_id`, `user_id`, `storage_key`, `kind`, `byte_size`, and non-sensitive
flags/timestamps) are intentionally **not** in this deny-list — the guard is
a deny-list, not an allow-list, so new fields are logged by default unless
they match a known-sensitive name or shape.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Field names that must never appear in a log line with their real value.
# Matched case-insensitively against the exact key name (after normalizing
# common separators) so both `refresh_token` and `refreshToken` are caught.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        # secrets
        "password",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "refresh_token_hash",
        "invite_token",
        "invite_token_hash",
        "reset_token",
        "reset_token_hash",
        "token_hash",
        "authorization",
        "jwt",
        "jwt_signing_key",
        "signing_key",
        "sid",
        # message content
        "content",
        "message_content",
        "message_body",
        "text",
        # PII
        "username",
        "email",
        "first_name",
        "last_name",
        "avatar_url",
        "last_seen",
        "recipient_id",
        "filename",
        "ip_address",
        "user_agent",
    }
)

# JWTs (three dot-separated base64url segments) are redacted wherever they
# appear — even under an unlisted key or embedded in free text — as
# defense-in-depth against accidental raw-token logging in an f-string.
_JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def _normalize_key(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()


def is_sensitive_key(key: str) -> bool:
    return _normalize_key(key) in _SENSITIVE_KEYS


def redact_text(text: str) -> str:
    """Redact JWT-shaped substrings from a free-text string."""

    return _JWT_RE.sub(REDACTED, text)


def redact_value(key: str, value: Any) -> Any:
    """Return a safe-to-log version of `value`, given its field `key`.

    A sensitive key redacts its entire value, including a nested dict/list
    subtree. Under a non-sensitive key the guard still recurses: dict values
    are redacted key-by-key, and list/tuple elements inherit the parent key
    (so a sensitive parent redacts every element) and are JWT-scrubbed. This
    guards the common `extra={"payload": model.model_dump()}` pattern, where
    secrets/PII/content would otherwise ride through under an innocuous key.
    """

    if is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [redact_value(key, item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `data` with every sensitive field redacted."""

    return {key: redact_value(key, value) for key, value in data.items()}
