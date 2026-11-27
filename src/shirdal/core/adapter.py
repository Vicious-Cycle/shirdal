from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from shirdal.core.events import ChatAction, ChatRef, MessageEvent, UpdateEvent


class AdapterError(Exception):
    """Base exception for transport adapter failures."""


class FloodWaitError(AdapterError):
    """Raised when Telegram rate-limits a request."""

    def __init__(self, seconds: float, message: str | None = None) -> None:
        self.seconds = float(seconds)
        super().__init__(message or f"FloodWait: retry after {self.seconds}s")

    @property
    def retry_after(self) -> float:
        """Alias of :attr:`seconds` (Bot API / Telethon-style name)."""
        return self.seconds


@dataclass(slots=True, frozen=True)
class DeviceProfile:
    """Clean client device fingerprint sent to Telegram during session creation."""

    device_model: str = "Desktop"
    system_version: str = "Windows 11"
    app_version: str = "5.8.3 x64"
    lang_code: str = "en"
    system_lang_code: str = "en-US"

    @classmethod
    def desktop(cls) -> DeviceProfile:
        return cls()

    @classmethod
    def macos(cls) -> DeviceProfile:
        return cls(
            device_model="MacBook Pro",
            system_version="macOS 15.1",
            app_version="11.4.0",
            lang_code="en",
            system_lang_code="en-US",
        )


@runtime_checkable
class TransportAdapter(Protocol):
    """Abstract MTProto transport interface for shirdal."""

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def invoke(self, method: str, **params: Any) -> Any: ...

    def listen(self) -> AsyncIterator[UpdateEvent]: ...

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> MessageEvent: ...

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent: ...

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int: ...

    async def send_media(
        self,
        chat_id: int | str,
        media: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
        progress: Any = None,
    ) -> MessageEvent: ...

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]: ...

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes: ...

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None: ...

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None: ...

    async def pin_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        silent: bool = True,
    ) -> None: ...

    async def ban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None: ...

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None: ...

    async def mute_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None: ...

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None: ...

    async def get_chat(self, chat_id: int | str) -> ChatRef: ...
