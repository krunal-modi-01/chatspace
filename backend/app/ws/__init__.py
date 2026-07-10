"""WebSocket connection manager package (T23).

`/v1/ws` — see `app.ws.router` for the endpoint, `app.ws.close_codes`
for the frozen close-code catalogue, and `app.ws.connection_manager`
for the per-process connection registry `app.main` drains on shutdown.
"""

from __future__ import annotations
