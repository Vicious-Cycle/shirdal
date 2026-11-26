from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import ChatAction, ChatRef, MessageEvent, UpdateEvent

BOT_API_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB


def _media_size_bytes(media: str | Path | bytes) -> int | None:
    if isinstance(media, (bytes, bytearray, memoryview)):
        return len(media)
    if isinstance(media, Path):
        return media.stat().st_size if media.is_file() else None
    if isinstance(media, str) and not media.startswith(("http://", "https://")):
        p = Path(media)
        return p.stat().st_size if p.is_file() else None
    return None


class HybridAdapter:
    """Routes standard bot traffic over `primary` (e.g. BotAPIAdapter) and large media (>50 MiB) over `mtproto`."""

    def __init__(
        self,
        primary: TransportAdapter,
        mtproto: TransportAdapter,
        *,
        large_file_threshold: int = BOT_API_MAX_BYTES,
    ) -> None:
        self.primary = primary
        self.mtproto = mtproto
        self.large_file_threshold = large_file_threshold

    @property
    def is_connected(self) -> bool:
        return self.primary.is_connected

    async def connect(self) -> None:
        await self.primary.connect()
        await self.mtproto.connect()

    async def disconnect(self) -> None:
        try:
            await self.primary.disconnect()
        finally:
            await self.mtproto.disconnect()

    async def invoke(self, method: str, **params: Any) -> Any:
        return await self.primary.invoke(method, **params)

    def listen(self) -> AsyncIterator[UpdateEvent]:
        return self.primary.listen()

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        return await self.primary.send_message(
            chat_id, text, reply_to=reply_to, parse_mode=parse_mode
        )

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        return await self.primary.edit_message(
            chat_id, message_id, text, parse_mode=parse_mode
        )

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        return await self.primary.delete_messages(chat_id, message_ids, revoke=revoke)

    async def send_media(
        self,
        chat_id: int | str,
        media: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
        progress: Any = None,
    ) -> MessageEvent:
        size = _media_size_bytes(media)
        target = (
            self.mtproto
            if size is not None and size > self.large_file_threshold
            else self.primary
        )
        return await target.send_media(
            chat_id,
            media,
            caption=caption,
            reply_to=reply_to,
            parse_mode=parse_mode,
            progress=progress,
        )

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        return await self.primary.send_album(
            chat_id, media_items, caption=caption, reply_to=reply_to, parse_mode=parse_mode
        )

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        return await self.primary.download_media(
            message, destination=destination, progress=progress
        )

    async def send_reaction(
        self, chat_id: int | str, message_id: int, emoji: str | None
    ) -> None:
        await self.primary.send_reaction(chat_id, message_id, emoji)

    async def send_chat_action(
        self, chat_id: int | str, action: ChatAction | str
    ) -> None:
        await self.primary.send_chat_action(chat_id, action)

    async def pin_message(
        self, chat_id: int | str, message_id: int, *, silent: bool = True
    ) -> None:
        await self.primary.pin_message(chat_id, message_id, silent=silent)

    async def ban_user(
        self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None
    ) -> None:
        await self.primary.ban_user(chat_id, user_id, until_date=until_date)

    async def unban_user(self, chat_id: int | str, user_id: int | str) -> None:
        await self.primary.unban_user(chat_id, user_id)

    async def mute_user(
        self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None
    ) -> None:
        await self.primary.mute_user(chat_id, user_id, until_date=until_date)

    async def kick_user(self, chat_id: int | str, user_id: int | str) -> None:
        await self.primary.kick_user(chat_id, user_id)

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        return await self.primary.get_chat(chat_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.primary, name)
