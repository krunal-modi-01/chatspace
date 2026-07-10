"""Per-process WebSocket connection registry + subscription bookkeeping (T23/T24).

Tracks every live `/v1/ws` connection on this instance and which
conversation topics (`chan:{channel_id}` / `dm:{a}:{b}`, from
`app.core.redis_keys`) it is subscribed to. This is in-process
bookkeeping only — it does **not** publish/subscribe to Redis pub/sub
itself (that is `app.ws.fanout.PubSubRelay`, T24's per-instance
subscriber) and does not persist anything; a connection disappears from
the registry the moment it disconnects.

`broadcast_to_topic` (T24) is the relay's only entry point into this
class: given an already-decoded fan-out event and the topic it arrived
on, it delivers that event to every *local* connection subscribed to
that topic — the last hop of "instance A publishes, instance B's
subscriber relays to its own local sockets" (no session affinity, F53).

Also owns the server-drain path: `close_all` closes every registered
connection with close code 1001 (going away), used by the application
lifespan on shutdown so in-flight connections get a clean, documented
close instead of a hard TCP drop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from starlette.websockets import WebSocket, WebSocketState

from app.core.ids import generate_id
from app.ws.close_codes import WSCloseCode

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectionState:
    """Bookkeeping for a single live `/v1/ws` connection."""

    connection_id: UUID
    websocket: WebSocket
    user_id: UUID
    session_id: UUID
    subscribed_topics: set[str] = field(default_factory=set)


class ConnectionManager:
    """In-process registry of live WS connections and their subscriptions.

    Not safe to share across processes/instances — each app instance owns
    its own registry (per CLAUDE.md's "1-2 stateless instances" posture);
    cross-instance fan-out is Redis pub/sub (T24), not this class.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, ConnectionState] = {}

    def register(self, websocket: WebSocket, *, user_id: UUID, session_id: UUID) -> ConnectionState:
        """Register a newly authenticated + accepted connection."""

        state = ConnectionState(
            connection_id=generate_id(),
            websocket=websocket,
            user_id=user_id,
            session_id=session_id,
        )
        self._connections[state.connection_id] = state
        logger.info(
            "ws connection registered",
            extra={
                "connection_id": str(state.connection_id),
                "user_id": str(user_id),
                "session_id": str(session_id),
            },
        )
        return state

    def unregister(self, state: ConnectionState) -> None:
        """Drop a connection and every subscription bookkeeping entry for it."""

        self._connections.pop(state.connection_id, None)
        logger.info(
            "ws connection unregistered",
            extra={
                "connection_id": str(state.connection_id),
                "user_id": str(state.user_id),
                "topic_count": len(state.subscribed_topics),
            },
        )

    def subscribe(self, state: ConnectionState, topic: str) -> None:
        """Record that `state`'s connection has joined `topic`."""

        state.subscribed_topics.add(topic)

    def unsubscribe(self, state: ConnectionState, topic: str) -> None:
        """Record that `state`'s connection has left `topic` (no-op if absent)."""

        state.subscribed_topics.discard(topic)

    def __len__(self) -> int:
        return len(self._connections)

    async def broadcast_to_topic(self, topic: str, payload: dict[str, object]) -> None:
        """Relay `payload` to every local connection currently subscribed to `topic`.

        Called once per received fan-out message by
        `app.ws.fanout.PubSubRelay` — never by request-handling code
        directly. Best-effort per connection: a send failure to one
        socket (already disconnected, transient error) is logged and
        skipped rather than aborting delivery to every other subscribed
        connection. `payload` must already be the exact wire envelope
        (no further transformation happens here).
        """

        for state in list(self._connections.values()):
            if topic not in state.subscribed_topics:
                continue
            if state.websocket.application_state != WebSocketState.CONNECTED:
                continue
            try:
                await state.websocket.send_json(payload)
            except Exception:  # noqa: BLE001 - best-effort fan-out, one bad socket must not block the rest
                logger.warning(
                    "failed to relay fan-out event to a local connection",
                    extra={"connection_id": str(state.connection_id), "topic": topic},
                )

    async def close_all(
        self, *, code: WSCloseCode = WSCloseCode.GOING_AWAY, reason: str = "server draining"
    ) -> None:
        """Close every registered connection (server shutdown/drain, 1001).

        Best-effort: a connection that is already gone/erroring on close is
        logged and skipped rather than allowed to block shutdown.
        """

        for state in list(self._connections.values()):
            try:
                await state.websocket.close(code=code, reason=reason)
            except Exception:  # noqa: BLE001 - best-effort drain, never block shutdown
                logger.warning(
                    "error closing ws connection during drain",
                    extra={"connection_id": str(state.connection_id)},
                )
            finally:
                self._connections.pop(state.connection_id, None)


# Process-wide singleton — one registry per app instance, mirroring the
# `get_engine`/`get_redis_client` singleton pattern (but not lru_cache'd
# since it is stateful mutable bookkeeping, not a lazily-built client).
connection_manager = ConnectionManager()
