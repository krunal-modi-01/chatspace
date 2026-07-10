"""`/v1/ws` client/server frame shapes (T23, frozen contract).

Client → server frames: `join`, `leave`, `typing`, `ping` — each of
`join`/`leave`/`typing` carries a `conversation` discriminated on `kind`
(`channel` | `dm`). Server → client frames relevant to T23: `error`
(non-fatal per-frame failure) and `pong` (heartbeat reply). The
`message.created`/`edited`/`deleted`/`typing`-delivery/`presence` server
frames are out of scope here (T24/T25/T26).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# --- Conversation targets (shared by join/leave/typing) ---------------------


class ChannelConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["channel"]
    channel_id: UUID


class DMConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dm"]
    user_id: UUID


Conversation = Annotated[
    ChannelConversation | DMConversation,
    Field(discriminator="kind"),
]


# --- Client → server frames --------------------------------------------------


class JoinFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["join"]
    conversation: Conversation


class LeaveFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["leave"]
    conversation: Conversation


class TypingFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["typing"]
    conversation: Conversation


class PingFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ping"]


ClientFrame = Annotated[
    JoinFrame | LeaveFrame | TypingFrame | PingFrame,
    Field(discriminator="type"),
]

client_frame_adapter: TypeAdapter[JoinFrame | LeaveFrame | TypingFrame | PingFrame] = TypeAdapter(
    ClientFrame
)


# --- Server → client frames relevant to T23 ----------------------------------


class ErrorFrameData(BaseModel):
    """`data` payload of a non-fatal per-frame `error` frame."""

    code: str
    detail: str


def error_frame(*, code: str, detail: str) -> dict[str, object]:
    """Build the `{"type": "error", "data": {...}}` server frame.

    Sent for a per-frame failure that does **not** close the socket (e.g.
    an unauthorized `join`) — the contract's non-fatal error path.
    `detail` must never contain message content, tokens, or PII.
    """

    return {"type": "error", "data": ErrorFrameData(code=code, detail=detail).model_dump()}


def pong_frame() -> dict[str, object]:
    """The heartbeat reply to a client `ping` frame."""

    return {"type": "pong"}
