"""Shared caller-IP extraction from a FastAPI `Request` (T27).

Split out of `app.api.auth` (which needs a strict IP-or-`None` for
`sessions.ip_address`, a Postgres `INET` column that cannot accept a
non-IP string like the test client's literal `"testclient"` host) so
`app.core.rate_limit_deps`'s `RateLimitScope.AUTH` keying (per IP +
attempted identifier) can reuse the exact same parsing rule without
duplicating it or importing a private, underscore-prefixed helper across
modules.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request


def extract_client_ip(request: Request) -> str | None:
    """Return the caller's IP, or `None` if the connecting host isn't a real IP.

    Anything that doesn't parse as an IPv4/IPv6 address (e.g. a hostname,
    or the test client's literal `"testclient"` host) is dropped rather
    than passed through, since callers of this function feed either a
    Postgres `INET` column (which raises a hard `DataError` on a non-IP
    value) or a rate-limit bucket key (where a `None` is coerced to a
    fixed fallback literal by the caller, never silently accepted as a
    wildcard IP).
    """

    host = request.client.host if request.client else None
    if host is None:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host
