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


class TelethonAdapter:
    """MTProto adapter backed by Telethon (lazy-imported) with clean DeviceProfile."""

    def __init__(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        *,
        device: DeviceProfile | None = None,
        session_string: str | None = None,
    ) -> None:
        try:
            from telethon import TelegramClient, events  # type: ignore[import-not-found]
            from telethon.sessions import StringSession  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AdapterError(
                "Telethon is not installed. Run: pip install 'shirdal[telethon]'"
            ) from exc

        profile = device or DeviceProfile.desktop()
        session: Any = (
            StringSession(session_string) if session_string is not None else session_name
        )

        self._events = events
        self._client = TelegramClient(
            session,
            api_id,
            api_hash,
            device_model=profile.device_model,
            system_version=profile.system_version,
            app_version=profile.app_version,
            lang_code=profile.lang_code,
            system_lang_code=profile.system_lang_code,
        )
        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._connected = False

        @self._client.on(events.NewMessage())
        async def _on_new_message(event: Any) -> None:
            await self._queue.put(
                UpdateEvent(
                    type=EventType.NEW_MESSAGE,
                    message=self._normalize_message(event.message),
                    raw=event,
                )
            )

        @self._client.on(events.MessageEdited())
        async def _on_edit_message(event: Any) -> None:
            await self._queue.put(
                UpdateEvent(
                    type=EventType.EDIT_MESSAGE,
                    message=self._normalize_message(event.message),
                    raw=event,
                )
            )

        @self._client.on(events.MessageDeleted())
        async def _on_delete_message(event: Any) -> None:
            await self._queue.put(
                UpdateEvent(
                    type=EventType.DELETE_MESSAGE,
                    message=None,
                    raw=event,
                )
            )

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client.is_connected()

    async def connect(self) -> None:
        await self._client.start()
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        await self._queue.put(None)
        await self._client.disconnect()

    def _map_error(self, exc: Exception) -> AdapterError:
        if exc.__class__.__name__ == "FloodWaitError":
            return FloodWaitError(getattr(exc, "seconds", 1))
        return AdapterError(str(exc))

    async def invoke(self, method: str, **params: Any) -> Any:
        try:
            from telethon.tl import functions  # type: ignore[import-not-found]

            obj: Any = functions
            for part in method.split("."):
                obj = getattr(obj, part, None)
                if obj is None:
                    raise AdapterError(f"Unknown Telethon TL function: {method}")
            return await self._client(obj(**params))
        except AdapterError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

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
                chat_id, text, reply_to=reply_to, parse_mode=parse_mode
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
            edited = await self._client.edit_message(
                chat_id, message_id, text, parse_mode=parse_mode
            )
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
            return len(res) if isinstance(res, list) else len(message_ids)
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
            sent = await self._client.send_file(
                chat_id,
                media,
                caption=caption,
                reply_to=reply_to,
                parse_mode=parse_mode,
                progress_callback=progress,
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
            sent_list = await self._client.send_file(
                chat_id,
                list(media_items),
                caption=caption,
                reply_to=reply_to,
                parse_mode=parse_mode,
            )
            if not isinstance(sent_list, list):
                sent_list = [sent_list]
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
                    target, file=str(destination), progress_callback=progress
                )
                return Path(out)
            buf = await self._client.download_media(
                target, file=bytes, progress_callback=progress
            )
            return buf if isinstance(buf, (bytes, bytearray)) else bytes(buf)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None:
        try:
            from telethon.tl import functions, types  # type: ignore[import-not-found]

            reaction = [types.ReactionEmoji(emoticon=emoji)] if emoji else []
            await self._client(
                functions.messages.SendReactionRequest(
                    peer=chat_id, msg_id=message_id, reaction=reaction
                )
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None:
        try:
            from telethon.tl import functions, types  # type: ignore[import-not-found]

            action_map = {
                ChatAction.TYPING: types.SendMessageTypingAction(),
                ChatAction.UPLOAD_PHOTO: types.SendMessageUploadPhotoAction(progress=0),
                ChatAction.UPLOAD_VIDEO: types.SendMessageUploadVideoAction(progress=0),
                ChatAction.UPLOAD_DOCUMENT: types.SendMessageUploadDocumentAction(progress=0),
                ChatAction.RECORD_VOICE: types.SendMessageRecordAudioAction(),
                ChatAction.CANCEL: types.SendMessageCancelAction(),
            }
            tl_action = action_map.get(str(action), types.SendMessageTypingAction())
            await self._client(
                functions.messages.SetTypingRequest(peer=chat_id, action=tl_action)
            )
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
            await self._client.pin_message(chat_id, message_id, notify=not silent)
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
            await self._client.edit_permissions(
                chat_id, user_id, view_messages=False, until_date=until_date
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        try:
            await self._client.edit_permissions(chat_id, user_id, view_messages=True)
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
            await self._client.edit_permissions(
                chat_id, user_id, send_messages=False, until_date=until_date
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        try:
            await self._client.kick_participant(chat_id, user_id)
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        try:
            entity = await self._client.get_entity(chat_id)
            ctype = "channel" if getattr(entity, "broadcast", False) else (
                "supergroup" if getattr(entity, "megagroup", False) else "private"
            )
            return ChatRef(
                id=getattr(entity, "id", 0),
                type=ctype,
                title=getattr(entity, "title", None) or getattr(entity, "first_name", None),
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

        return MessageEvent(
            id=msg.id,
            chat=ChatRef(id=msg.chat_id or 0),
            sender=UserRef(id=msg.sender_id or 0, is_self=bool(msg.out)),
            text=msg.raw_text or "",
            media=media_ref,
            reply_to_id=getattr(msg, "reply_to_msg_id", None),
            is_outgoing=bool(msg.out),
            raw=msg,
        )
