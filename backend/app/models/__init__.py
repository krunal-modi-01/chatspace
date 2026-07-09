"""SQLAlchemy ORM models.

`Session`/`User` are the two models needed by T10 (session store + auth
dependency); `PasswordResetToken` is added by T16 (password reset).
`Channel`/`ChannelMember` are added by T18 (channel create/get/public
browse). `Message`/`Attachment` are added by T21 (message send/edit/
delete/history). Import through this package (`from app.models import
Session, User, PasswordResetToken, Channel, ChannelMember, Message,
Attachment`) rather than the submodules directly, so `app.db.base.Base
.metadata` sees every mapped class Alembic/tests need to inspect.
"""

from __future__ import annotations

from app.models.attachment import Attachment, AttachmentKind
from app.models.channel import Channel
from app.models.channel_member import ChannelMember, ChannelMemberRole
from app.models.message import Message
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User

__all__ = [
    "Attachment",
    "AttachmentKind",
    "Channel",
    "ChannelMember",
    "ChannelMemberRole",
    "Message",
    "PasswordResetToken",
    "Session",
    "User",
]
