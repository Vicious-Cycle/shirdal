from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any, AsyncIterator

from shirdal.core.adapter import FloodWaitError
from shirdal.core.events import (
    ChatAction,
    ChatRef,
    EventType,
    MediaRef,
    MessageEvent,
    UpdateEvent,
    UserRef,
)


class MockAdapter:
    """In-memory adapter for local testing without Telegram credentials."""

    def __init__(self) -> None:
        self._connected = False
        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._next_msg_id = 100
        self._queued_flood_waits: list[float] = []
        self.sent_messages: list[MessageEvent] = []
        self.edited_messages: list[MessageEvent] = []
        self.deleted_ids: list[tuple[int | str, list[int]]] = []
        self.sent_media: list[tuple[int | str, str | Path | bytes, str | None]] = []
        self.sent_albums: list[tuple[int | str, list[str | Path | bytes], str | None]] = []
        self.reactions: list[tuple[int | str, int, str | None]] = []
        self.chat_actions: list[tuple[int | str, str]] = []
        self.pinned_messages: list[tuple[int | str, int, bool]] = []
        self.banned_users: list[tuple[int | str, int | str, int | None]] = []
        self.unbanned_users: list[tuple[int | str, int | str]] = []
        self.muted_users: list[tuple[int | str, int | str, int | None]] = []
        self.kicked_users: list[tuple[int | str, int | str]] = []
        self.get_chat_calls: int = 0
        self.chats: dict[int | str, ChatRef] = {}
        self.invoked_methods: list[tuple[str, dict[str, Any]]] = []
        self._mock_media_bytes: bytes = b"SHIRDAL_MOCK_MEDIA"

    def queue_flood_wait(self, seconds: float) -> None:
        self._queued_flood_waits.append(seconds)

    def _maybe_raise_flood(self) -> None:
        if self._queued_flood_waits:
            raise FloodWaitError(self._queued_flood_waits.pop(0))

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        await self._queue.put(None)

    async def push_incoming(
        self,
        text: str,
        *,
        chat_id: int = 1,
        sender_id: int = 1,
        is_outgoing: bool = True,
        media: MediaRef | None = None,
        event_type: EventType = EventType.NEW_MESSAGE,
    ) -> UpdateEvent:
        self._next_msg_id += 1
        msg = MessageEvent(
            id=self._next_msg_id,
            chat=ChatRef(id=chat_id, type="private"),
            sender=UserRef(id=sender_id, is_self=is_outgoing),
            text=text,
            media=media,
            is_outgoing=is_outgoing,
        )
        event = UpdateEvent(type=event_type, message=msg)
        await self._queue.put(event)
        return event

    async def invoke(self, method: str, **params: Any) -> Any:
        self._maybe_raise_flood()
        self.invoked_methods.append((method, params))
        return {"ok": True, "method": method, "params": params}

    async def listen(self) -> AsyncIterator[UpdateEvent]:
        while self._connected:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        self._maybe_raise_flood()
        self._next_msg_id += 1
        msg = MessageEvent(
            id=self._next_msg_id,
            chat=ChatRef(id=int(chat_id) if isinstance(chat_id, int) else 0),
            sender=UserRef(id=0, is_self=True),
            text=text,
            reply_to_id=reply_to,
            is_outgoing=True,
        )
        self.sent_messages.append(msg)
        return msg

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        self._maybe_raise_flood()
        msg = MessageEvent(
            id=message_id,
            chat=ChatRef(id=int(chat_id) if isinstance(chat_id, int) else 0),
            sender=UserRef(id=0, is_self=True),
            text=text,
            is_outgoing=True,
        )
        self.edited_messages.append(msg)
        return msg

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        self._maybe_raise_flood()
        self.deleted_ids.append((chat_id, list(message_ids)))
        return len(message_ids)

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
        self._maybe_raise_flood()
        if progress is not None:
            await progress(len(self._mock_media_bytes), len(self._mock_media_bytes))
        self._next_msg_id += 1
        self.sent_media.append((chat_id, media, caption))
        msg = MessageEvent(
            id=self._next_msg_id,
            chat=ChatRef(id=int(chat_id) if isinstance(chat_id, int) else 0),
            sender=UserRef(id=0, is_self=True),
            text=caption or "",
            media=MediaRef(media_type="document"),
            reply_to_id=reply_to,
            is_outgoing=True,
        )
        self.sent_messages.append(msg)
        return msg

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        self._maybe_raise_flood()
        items = list(media_items)
        self.sent_albums.append((chat_id, items, caption))
        out: list[MessageEvent] = []
        for idx, _ in enumerate(items):
            self._next_msg_id += 1
            msg = MessageEvent(
                id=self._next_msg_id,
                chat=ChatRef(id=int(chat_id) if isinstance(chat_id, int) else 0),
                sender=UserRef(id=0, is_self=True),
                text=(caption or "") if idx == 0 else "",
                media=MediaRef(media_type="document"),
                reply_to_id=reply_to,
                is_outgoing=True,
            )
            self.sent_messages.append(msg)
            out.append(msg)
        return out

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        self._maybe_raise_flood()
        if progress is not None:
            await progress(len(self._mock_media_bytes), len(self._mock_media_bytes))
        if destination is not None:
            dest = Path(destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self._mock_media_bytes)
            return dest
        return self._mock_media_bytes

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None:
        self._maybe_raise_flood()
        self.reactions.append((chat_id, message_id, emoji))

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None:
        self._maybe_raise_flood()
        self.chat_actions.append((chat_id, str(action)))

    async def pin_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        silent: bool = True,
    ) -> None:
        self._maybe_raise_flood()
        self.pinned_messages.append((chat_id, message_id, silent))

    async def ban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        self._maybe_raise_flood()
        self.banned_users.append((chat_id, user_id, until_date))

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        self._maybe_raise_flood()
        self.unbanned_users.append((chat_id, user_id))

    async def mute_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        self._maybe_raise_flood()
        self.muted_users.append((chat_id, user_id, until_date))

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        self._maybe_raise_flood()
        self.kicked_users.append((chat_id, user_id))

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        self._maybe_raise_flood()
        self.get_chat_calls += 1
        if chat_id in self.chats:
            return self.chats[chat_id]
        cid = int(chat_id) if isinstance(chat_id, int) else 0
        return ChatRef(id=cid, type="supergroup", title=f"Chat {chat_id}")
