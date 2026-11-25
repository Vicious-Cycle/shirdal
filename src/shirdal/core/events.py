from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    NEW_MESSAGE = "new_message"
    EDIT_MESSAGE = "edit_message"
    DELETE_MESSAGE = "delete_message"
    RAW = "raw"


class ChatAction(StrEnum):
    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"
    UPLOAD_VIDEO = "upload_video"
    UPLOAD_DOCUMENT = "upload_document"
    RECORD_VOICE = "record_voice"
    CANCEL = "cancel"


@dataclass(slots=True, frozen=True)
class MediaRef:
    media_type: str  # photo | video | document | voice | sticker | audio
    file_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    file_size: int | None = None


@dataclass(slots=True, frozen=True)
class UserRef:
    id: int
    username: str | None = None
    first_name: str | None = None
    is_self: bool = False


@dataclass(slots=True, frozen=True)
class ChatRef:
    id: int
    type: str = "private"  # private | group | supergroup | channel
    title: str | None = None


@dataclass(slots=True)
class MessageEvent:
    id: int
    chat: ChatRef
    sender: UserRef | None
    text: str = ""
    media: MediaRef | None = None
    reply_to_id: int | None = None
    is_outgoing: bool = False
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Any = None


@dataclass(slots=True)
class UpdateEvent:
    type: EventType
    message: MessageEvent | None = None
    raw: Any = None
