from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from shirdal.core.adapter import AdapterError, DeviceProfile, FloodWaitError
from shirdal.core.events import (
    ChatAction,
    ChatRef,
    EventType,
    MediaRef,
    MessageEvent,
    UpdateEvent,
    UserRef,
)


class HydrogramAdapter:
    """MTProto adapter backed by Hydrogram / Pyrogram-compatible client (lazy-imported)."""

    def __init__(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        *,
        device: DeviceProfile | None = None,
        session_string: str | None = None,
        bot_token: str | None = None,
    ) -> None:
        try:
            from hydrogram import Client  # type: ignore[import-not-found]
        except ImportError:
            try:
                from pyrogram import Client  # type: ignore[import-not-found]
            except ImportError as exc:
                raise AdapterError(
                    "Hydrogram/Pyrogram is not installed. Run: pip install 'shirdal[hydrogram]'"
                ) from exc

        profile = device or DeviceProfile.desktop()
        kwargs: dict[str, Any] = {
            "api_id": api_id,
            "api_hash": api_hash,
            "device_model": profile.device_model,
            "system_version": profile.system_version,
            "app_version": profile.app_version,
            "lang_code": profile.lang_code,
        }
        if session_string is not None:
            kwargs["session_string"] = session_string
        if bot_token is not None:
            kwargs["bot_token"] = bot_token

        self._client = Client(session_name, **kwargs)
        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._connected = False

        @self._client.on_message()
        async def _on_message(_: Any, msg: Any) -> None:
            await self._queue.put(
                UpdateEvent(
                    type=EventType.NEW_MESSAGE,
                    message=self._normalize_message(msg),
                    raw=msg,
                )
            )

        @self._client.on_edited_message()
        async def _on_edited_message(_: Any, msg: Any) -> None:
            await self._queue.put(
                UpdateEvent(
                    type=EventType.EDIT_MESSAGE,
                    message=self._normalize_message(msg),
                    raw=msg,
                )
            )

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._client.start()
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        await self._queue.put(None)
        await self._client.stop()

    def _map_error(self, exc: Exception) -> AdapterError:
        if "FloodWait" in exc.__class__.__name__:
            return FloodWaitError(getattr(exc, "value", getattr(exc, "seconds", 1)))
        return AdapterError(str(exc))

    async def invoke(self, method: str, **params: Any) -> Any:
        raise AdapterError(f"Direct raw invoke '{method}' requires TL raw object.")

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
        try:
            sent = await self._client.send_message(
                chat_id, text, reply_to_message_id=reply_to
            )
            return self._normalize_message(sent)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        try:
            edited = await self._client.edit_message_text(chat_id, message_id, text)
            return self._normalize_message(edited)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        try:
            res = await self._client.delete_messages(chat_id, message_ids, revoke=revoke)
            return int(res) if isinstance(res, int) else len(message_ids)
        except Exception as exc:
            raise self._map_error(exc) from exc

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
        try:
            sent = await self._client.send_document(
                chat_id,
                media,
                caption=caption,
                reply_to_message_id=reply_to,
                progress=progress,
            )
            return self._normalize_message(sent)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Any,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        try:
            from hydrogram.types import InputMediaDocument  # type: ignore[import-not-found]

            group = [
                InputMediaDocument(item, caption=caption if idx == 0 else "")
                for idx, item in enumerate(media_items)
            ]
            sent_list = await self._client.send_media_group(
                chat_id, group, reply_to_message_id=reply_to
            )
            return [self._normalize_message(m) for m in sent_list]
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        try:
            target = message.raw if message.raw is not None else message.id
            if destination is not None:
                out = await self._client.download_media(
                    target, file_name=str(destination), progress=progress
                )
                return Path(out)
            buf = await self._client.download_media(
                target, in_memory=True, progress=progress
            )
            return buf.getvalue() if hasattr(buf, "getvalue") else bytes(buf)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None:
        try:
            await self._client.send_reaction(chat_id, message_id, emoji=emoji or "")
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None:
        try:
            await self._client.send_chat_action(chat_id, str(action))
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def pin_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        silent: bool = True,
    ) -> None:
        try:
            await self._client.pin_chat_message(
                chat_id, message_id, disable_notification=silent
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def ban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        try:
            await self._client.ban_chat_member(chat_id, user_id)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        try:
            await self._client.unban_chat_member(chat_id, user_id)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def mute_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        try:
            from hydrogram.types import ChatPermissions  # type: ignore[import-not-found]

            await self._client.restrict_chat_member(
                chat_id, user_id, ChatPermissions()
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        await self.ban_user(chat_id, user_id)
        await self.unban_user(chat_id, user_id)

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        try:
            chat = await self._client.get_chat(chat_id)
            return ChatRef(
                id=chat.id,
                type=str(getattr(chat, "type", "private")),
                title=getattr(chat, "title", None) or getattr(chat, "first_name", None),
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    @staticmethod
    def _normalize_message(msg: Any) -> MessageEvent:
        media_ref = None
        if getattr(msg, "photo", None) is not None:
            media_ref = MediaRef(media_type="photo")
        elif getattr(msg, "video", None) is not None:
            media_ref = MediaRef(media_type="video")
        elif getattr(msg, "voice", None) is not None:
            media_ref = MediaRef(media_type="voice")
        elif getattr(msg, "sticker", None) is not None:
            media_ref = MediaRef(media_type="sticker")
        elif getattr(msg, "document", None) is not None:
            media_ref = MediaRef(media_type="document")

        chat_id = msg.chat.id if getattr(msg, "chat", None) else 0
        from_user = getattr(msg, "from_user", None)
        sender_id = from_user.id if from_user else 0
        return MessageEvent(
            id=msg.id,
            chat=ChatRef(id=chat_id),
            sender=UserRef(id=sender_id, is_self=bool(getattr(msg, "outgoing", False))),
            text=msg.text or msg.caption or "",
            media=media_ref,
            reply_to_id=getattr(msg, "reply_to_message_id", None),
            is_outgoing=bool(getattr(msg, "outgoing", False)),
            raw=msg,
        )
