"""Manual request-body parsing for the frozen `400` "malformed body" clause.

Per the frozen API contract, most auth endpoints (including all three of
T16's `/v1/auth/password*` routes) distinguish a **malformed body** (`400`)
from a **semantically invalid field value** (`422`, e.g. F23 password
policy). FastAPI's default behavior for a Pydantic-typed body parameter
folds both cases into a single `422 RequestValidationError` — which does
not let a route return `400` for "missing/wrong-type field" while still
reserving `422` for its own business-rule checks (e.g.
`enforce_password_policy`).

The pattern here: routes declare their body as a plain `dict[str, Any]`
(so FastAPI still requires a JSON object, but performs no field-level
validation), then call `parse_body(Schema, payload)` to run the real
Pydantic validation themselves. A validation failure raises
`MalformedBodyError`, which `app.core.errors.install_error_handlers`
maps to the frozen `400 problem+json` shape (with the same `errors[]`
field-detail list `RequestValidationError` would have produced).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError


class MalformedBodyError(Exception):
    """Raised when a request body fails schema validation (frozen `400`).

    `errors` is a list of `{"field": ..., "detail": ...}` dicts, ready to
    drop into the RFC 7807 `errors[]` array of a 400 problem+json body —
    mirrors `app.core.password_policy.PasswordPolicyError`'s shape exactly,
    just at a different status code.
    """

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Request body is malformed.")


def parse_body[ModelT: BaseModel](model: type[ModelT], raw: dict[str, Any]) -> ModelT:
    """Validate `raw` against `model`, raising `MalformedBodyError` on failure.

    Never echoes the raw (possibly secret-bearing, e.g. `new_password`)
    field values in the resulting error detail — only the field name and
    Pydantic's own (value-free) violation message, matching
    `validation_exception_handler`'s existing behavior for the automatic
    `422` path.
    """

    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "detail": error["msg"],
            }
            for error in exc.errors()
        ]
        raise MalformedBodyError(errors) from exc
