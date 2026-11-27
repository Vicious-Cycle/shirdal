from __future__ import annotations

import asyncio
import html
import http.client
import queue
import json
import mimetypes
import ssl
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from shirdal.core.adapter import AdapterError, FloodWaitError
from shirdal.core.events import (
    ChatAction,
    ChatRef,
    EventType,
    MediaRef,
    MessageEvent,
    UpdateEvent,
    UserRef,
)

try:
    import msgspec as _msgspec  # type: ignore[import-not-found]

    def _json_dumps(obj: Any) -> bytes:
        return _msgspec.json.encode(obj)

    def _json_loads(data: bytes) -> Any:
        return _msgspec.json.decode(data)
except ImportError:

    def _json_dumps(obj: Any) -> bytes:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def _json_loads(data: bytes) -> Any:
        return json.loads(data.decode("utf-8"))


_PARSE_MODE_MAP = {
    "html": "HTML",
    "markdown": "MarkdownV2",
    "md": "MarkdownV2",
    "markdownv2": "MarkdownV2",
}




class ButtonStyle(StrEnum):
    """Official Telegram Bot API 9.4+ button styles."""

    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"


_VALID_BUTTON_STYLES = {s.value for s in ButtonStyle}


def _normalize_button_style(style: ButtonStyle | str | None) -> str | None:
    if style is None:
        return None
    normalized = str(style).strip().lower()
    if normalized not in _VALID_BUTTON_STYLES:
        raise ValueError(
            f"Invalid button style {style!r}. Expected one of: primary, success, danger."
        )
    return normalized


def custom_emoji(emoji_id: str, fallback: str = "✨") -> str:
    """Render a Telegram Premium/Custom Emoji tag for HTML parse_mode."""
    eid = str(emoji_id).strip()
    if not eid:
        raise ValueError("emoji_id must not be empty.")
    return f'<tg-emoji emoji-id="{html.escape(eid, quote=True)}">{html.escape(fallback)}</tg-emoji>'


def custom_emoji_entity(offset: int, length: int, emoji_id: str) -> dict[str, Any]:
    """Build a raw Telegram MessageEntity dict for a custom emoji."""
    eid = str(emoji_id).strip()
    if not eid:
        raise ValueError("emoji_id must not be empty.")
    return {
        "type": "custom_emoji",
        "offset": int(offset),
        "length": int(length),
        "custom_emoji_id": eid,
    }


def date_time(unix_time: int, fallback: str = "", *, format: str | None = None) -> str:
    """Render a Telegram Bot API 9.5+ <tg-time> HTML tag for localized date/time."""
    ts = int(unix_time)
    text = html.escape(fallback) if fallback else str(ts)
    if format is not None:
        return f'<tg-time unix="{ts}" format="{html.escape(format, quote=True)}">{text}</tg-time>'
    return f'<tg-time unix="{ts}">{text}</tg-time>'


def date_time_entity(
    offset: int,
    length: int,
    unix_time: int,
    *,
    format: str | None = None,
) -> dict[str, Any]:
    """Build a raw Telegram Bot API 9.5+ MessageEntity dict for date_time."""
    ent: dict[str, Any] = {
        "type": "date_time",
        "offset": int(offset),
        "length": int(length),
        "unix_time": int(unix_time),
    }
    if format is not None:
        ent["date_time_format"] = format
    return ent


def rich_message(
    *,
    html: str | None = None,
    markdown: str | None = None,
    blocks: Sequence[dict[str, Any]] | None = None,
    media: Sequence[dict[str, Any]] | None = None,
    is_rtl: bool | None = None,
    skip_entity_detection: bool | None = None,
) -> dict[str, Any]:
    """Build a Telegram Bot API 10.1+ InputRichMessage dictionary."""
    provided = sum(x is not None for x in (html, markdown, blocks))
    if provided != 1:
        raise ValueError(
            "InputRichMessage requires exactly one of: html, markdown, or blocks."
        )
    obj: dict[str, Any] = {}
    if html is not None:
        obj["html"] = html
    elif markdown is not None:
        obj["markdown"] = markdown
    else:
        obj["blocks"] = list(blocks or [])
    if media is not None:
        obj["media"] = list(media)
    if is_rtl is not None:
        obj["is_rtl"] = bool(is_rtl)
    if skip_entity_detection is not None:
        obj["skip_entity_detection"] = bool(skip_entity_detection)
    return obj


def rich_heading(text: str, size: int = 1) -> dict[str, Any]:
    """Build an InputRichBlockSectionHeading block (size 1-6)."""
    if not 1 <= int(size) <= 6:
        raise ValueError("Heading size must be between 1 and 6.")
    return {"type": "heading", "text": text, "size": int(size)}


def rich_paragraph(text: str) -> dict[str, Any]:
    """Build an InputRichBlockParagraph block."""
    return {"type": "paragraph", "text": text}


def rich_code(text: str, *, language: str | None = None) -> dict[str, Any]:
    """Build an InputRichBlockPreformatted code block."""
    blk: dict[str, Any] = {"type": "pre", "text": text}
    if language is not None:
        blk["language"] = language
    return blk


def rich_footer(text: str) -> dict[str, Any]:
    """Build an InputRichBlockFooter block."""
    return {"type": "footer", "text": text}


def rich_divider() -> dict[str, Any]:
    """Build an InputRichBlockDivider block."""
    return {"type": "divider"}


def rich_math(expression: str) -> dict[str, Any]:
    """Build an InputRichBlockMathematicalExpression block."""
    return {"type": "mathematical_expression", "expression": expression}


def rich_thinking(text: str = "Thinking...") -> dict[str, Any]:
    """Build a draft-only InputRichBlockThinking block for sendRichMessageDraft."""
    return {"type": "thinking", "text": text}


def rich_blockquote(
    content: str | Sequence[dict[str, Any]],
    *,
    credit: str | None = None,
    expandable: bool = False,
) -> dict[str, Any]:
    """Build a blockquote or expandable_blockquote InputRichBlock."""
    if expandable:
        blk: dict[str, Any] = {
            "type": "expandable_blockquote",
            "blocks": [rich_paragraph(content)] if isinstance(content, str) else list(content),
        }
    else:
        blk = {
            "type": "blockquote",
            "blocks": [rich_paragraph(content)] if isinstance(content, str) else list(content),
        }
    if credit is not None:
        blk["credit"] = credit
    return blk


def rich_details(
    summary: str,
    blocks: Sequence[dict[str, Any]],
    *,
    is_open: bool = False,
) -> dict[str, Any]:
    """Build a collapsible InputRichBlockDetails block."""
    blk: dict[str, Any] = {
        "type": "details",
        "summary": summary,
        "blocks": list(blocks),
    }
    if is_open:
        blk["is_open"] = True
    return blk


def rich_table(
    rows: Sequence[Sequence[dict[str, Any] | str]],
    *,
    headers: Sequence[dict[str, Any] | str] | None = None,
    caption: str | None = None,
    bordered: bool = True,
    striped: bool = True,
    compact: bool = False,
) -> dict[str, Any]:
    """Build an InputRichBlockTable block."""
    cells: list[list[dict[str, Any]]] = []
    if headers is not None:
        cells.append(
            [{"text": c, "is_header": True} if isinstance(c, str) else {**c, "is_header": True} for c in headers]
        )
    for row in rows:
        cells.append(
            [{"text": c} if isinstance(c, str) else dict(c) for c in row]
        )
    blk: dict[str, Any] = {
        "type": "table",
        "cells": cells,
        "is_bordered": bordered,
        "is_striped": striped,
        "is_compact": compact,
    }
    if caption is not None:
        blk["caption"] = caption
    return blk


def rich_buttons(
    buttons: Sequence[dict[str, Any]],
    *,
    align: str | None = None,
) -> dict[str, Any]:
    """Build an InputRichBlockButtons block (1-8 RichMessageButton items)."""
    blk: dict[str, Any] = {"type": "buttons", "buttons": list(buttons)}
    if align is not None:
        blk["align"] = align
    return blk


def button(
    text: str,
    callback_data: str | None = None,
    *,
    url: str | None = None,
    style: ButtonStyle | str | None = None,
    icon_custom_emoji_id: str | None = None,
    icon: str | None = None,
    disabled: bool = False,
    web_app_url: str | None = None,
    copy_text: str | None = None,
    switch_inline_query: str | None = None,
    switch_inline_query_current_chat: str | None = None,
) -> dict[str, Any]:
    """Build an InlineKeyboardButton dictionary (supports Bot API 9.4+ colors & custom emoji)."""
    btn: dict[str, Any] = {"text": text}
    if callback_data is not None:
        btn["callback_data"] = callback_data
    if url is not None:
        btn["url"] = url
    norm_style = _normalize_button_style(style)
    if norm_style is not None:
        btn["style"] = norm_style
    emoji_id = icon_custom_emoji_id if icon_custom_emoji_id is not None else icon
    if emoji_id is not None:
        btn["icon_custom_emoji_id"] = str(emoji_id).strip()
    if disabled:
        btn["disabled"] = True
    if web_app_url is not None:
        btn["web_app"] = {"url": web_app_url}
    if copy_text is not None:
        btn["copy_text"] = {"text": copy_text}
    if switch_inline_query is not None:
        btn["switch_inline_query"] = switch_inline_query
    if switch_inline_query_current_chat is not None:
        btn["switch_inline_query_current_chat"] = switch_inline_query_current_chat
    return btn


def inline_keyboard(
    rows: Sequence[Sequence[dict[str, Any]]],
    *,
    force_reply: bool | None = None,
) -> dict[str, Any]:
    """Build an InlineKeyboardMarkup dictionary."""
    markup: dict[str, Any] = {"inline_keyboard": [list(row) for row in rows]}
    if force_reply is not None:
        markup["force_reply"] = bool(force_reply)
    return markup


def reply_button(
    text: str,
    *,
    style: ButtonStyle | str | None = None,
    icon_custom_emoji_id: str | None = None,
    icon: str | None = None,
    request_contact: bool = False,
    request_location: bool = False,
    web_app_url: str | None = None,
) -> dict[str, Any]:
    """Build a KeyboardButton dictionary (supports Bot API 9.4+ colors & custom emoji)."""
    btn: dict[str, Any] = {"text": text}
    norm_style = _normalize_button_style(style)
    if norm_style is not None:
        btn["style"] = norm_style
    emoji_id = icon_custom_emoji_id if icon_custom_emoji_id is not None else icon
    if emoji_id is not None:
        btn["icon_custom_emoji_id"] = str(emoji_id).strip()
    if request_contact:
        btn["request_contact"] = True
    if request_location:
        btn["request_location"] = True
    if web_app_url is not None:
        btn["web_app"] = {"url": web_app_url}
    return btn


def reply_keyboard(
    rows: Sequence[Sequence[dict[str, Any] | str]],
    *,
    resize_keyboard: bool = True,
    one_time_keyboard: bool = False,
    is_persistent: bool = False,
    input_field_placeholder: str | None = None,
    selective: bool = False,
    force_reply: bool | None = None,
) -> dict[str, Any]:
    """Build a ReplyKeyboardMarkup dictionary."""
    keyboard_rows: list[list[dict[str, Any]]] = []
    for row in rows:
        keyboard_rows.append(
            [{"text": cell} if isinstance(cell, str) else dict(cell) for cell in row]
        )
    markup: dict[str, Any] = {
        "keyboard": keyboard_rows,
        "resize_keyboard": resize_keyboard,
    }
    if one_time_keyboard:
        markup["one_time_keyboard"] = True
    if is_persistent:
        markup["is_persistent"] = True
    if input_field_placeholder is not None:
        markup["input_field_placeholder"] = input_field_placeholder
    if selective:
        markup["selective"] = True
    if force_reply is not None:
        markup["force_reply"] = bool(force_reply)
    return markup


class BotAPIAdapter:
    """Zero-dependency, Keep-Alive Telegram Bot API adapter for shirdal."""

    def __init__(
        self,
        bot_token: str,
        *,
        base_url: str = "https://api.telegram.org",
        poll_timeout: int = 30,
        allowed_updates: Sequence[str] | None = None,
        pool_size: int = 4,
        fetch_me: bool = True,
    ) -> None:
        token = bot_token.strip()
        if not token or ":" not in token:
            raise AdapterError("Invalid bot_token format. Expected '<id>:<secret>'.")

        self.bot_token = token
        parsed = urlparse(base_url.rstrip("/"))
        self._scheme = parsed.scheme or "https"
        self._host = parsed.hostname or "api.telegram.org"
        self._port = parsed.port or (443 if self._scheme == "https" else 80)
        self._base_path = f"{parsed.path}/bot{token}"
        self._file_path = f"{parsed.path}/file/bot{token}"

        self._poll_timeout = max(1, int(poll_timeout))
        self._allowed_updates = list(
            allowed_updates or ("message", "edited_message", "channel_post", "edited_channel_post", "callback_query", "inline_query")
        )
        self._pool_size = max(1, int(pool_size))
        self._ssl_ctx = ssl.create_default_context() if self._scheme == "https" else None

        self._conn_pool: queue.LifoQueue[http.client.HTTPConnection] = queue.LifoQueue(
            maxsize=self._pool_size
        )
        self._pool_lock: asyncio.Lock | None = None
        self._poll_conn: http.client.HTTPConnection | None = None

        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._poller_task: asyncio.Task[Any] | None = None
        self._connected = False
        self._offset = 0
        self._fetch_me = fetch_me
        self.bot_id: int | None = None
        self.bot_username: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _new_connection(self, timeout: float) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host,
                self._port,
                timeout=timeout,
                context=self._ssl_ctx,
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=timeout)

    def _request_sync(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float = 30.0,
        dedicated_conn: http.client.HTTPConnection | None = None,
    ) -> Any:
        path = f"{self._base_path}/{method}"
        headers: dict[str, str] = {"Connection": "keep-alive"}
        body: bytes

        if files:
            boundary = f"----ShirdalBoundary{uuid.uuid4().hex}"
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            body = self._encode_multipart(boundary, payload or {}, files)
        else:
            headers["Content-Type"] = "application/json"
            body = _json_dumps(payload or {})

        conn = dedicated_conn
        borrowed = False
        if conn is None:
            try:
                conn = self._conn_pool.get_nowait()
            except queue.Empty:
                conn = self._new_connection(timeout)
            borrowed = True

        try:
            for attempt in range(2):
                try:
                    conn.request("POST", path, body=body, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read()
                    status = resp.status
                    break
                except (http.client.HTTPException, OSError):
                    conn.close()
                    if attempt == 1:
                        raise
                    conn = self._new_connection(timeout)
            data = _json_loads(raw)
        except (http.client.HTTPException, OSError, ValueError) as exc:
            raise AdapterError(f"Bot API request failed ({method}): {exc}") from exc
        finally:
            if borrowed:
                try:
                    self._conn_pool.put_nowait(conn)
                except queue.Full:
                    conn.close()

        if not data.get("ok", False):
            params = data.get("parameters") or {}
            retry_after = params.get("retry_after")
            if status == 429 or retry_after is not None:
                raise FloodWaitError(float(retry_after or 1), data.get("description"))
            raise AdapterError(f"Telegram Bot API error ({method}): {data.get('description', status)}")
        return data.get("result")

    @staticmethod
    def _encode_multipart(
        boundary: str,
        fields: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
    ) -> bytes:
        chunks: list[bytes] = []
        b = boundary.encode("ascii")
        for key, value in fields.items():
            if value is None:
                continue
            val_str = (
                _json_dumps(value).decode("utf-8")
                if isinstance(value, (dict, list))
                else str(value)
            )
            chunks.append(
                b"--"
                + b
                + b'\r\nContent-Disposition: form-data; name="'
                + key.encode("utf-8")
                + b'"\r\n\r\n'
                + val_str.encode("utf-8")
                + b"\r\n"
            )
        for field_name, (filename, content, mime) in files.items():
            chunks.append(
                b"--"
                + b
                + b'\r\nContent-Disposition: form-data; name="'
                + field_name.encode("utf-8")
                + b'"; filename="'
                + filename.encode("utf-8")
                + b'"\r\nContent-Type: '
                + mime.encode("ascii")
                + b"\r\n\r\n"
                + content
                + b"\r\n"
            )
        chunks.append(b"--" + b + b"--\r\n")
        return b"".join(chunks)

    async def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Public Bot API method call (accepts a payload dict or keyword arguments)."""
        data = dict(payload) if payload is not None else {}
        if kwargs:
            data.update(kwargs)
        return await self._call(method, data or None)

    async def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        return await asyncio.to_thread(
            self._request_sync,
            method,
            payload,
            files=files,
            timeout=timeout,
        )

    async def connect(self) -> None:
        if self._connected:
            return
        if self._fetch_me:
            me = await self._call("getMe")
            if isinstance(me, dict):
                self.bot_id = int(me.get("id", 0)) or None
                self.bot_username = me.get("username")
        self._connected = True
        self._poll_conn = self._new_connection(float(self._poll_timeout + 10))
        self._poller_task = asyncio.create_task(self._poll_loop())

    async def disconnect(self) -> None:
        self._connected = False
        if self._poller_task is not None:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass
            self._poller_task = None

        if self._poll_conn is not None:
            self._poll_conn.close()
            self._poll_conn = None

        while True:
            try:
                self._conn_pool.get_nowait().close()
            except queue.Empty:
                break

        await self._queue.put(None)

    async def _poll_loop(self) -> None:
        while self._connected:
            try:
                updates = await asyncio.to_thread(
                    self._request_sync,
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self._poll_timeout,
                        "allowed_updates": self._allowed_updates,
                    },
                    timeout=float(self._poll_timeout + 10),
                    dedicated_conn=self._poll_conn,
                )
                if isinstance(updates, list):
                    for upd in updates:
                        upd_id = int(upd.get("update_id", 0))
                        if upd_id >= self._offset:
                            self._offset = upd_id + 1
                        event = self._normalize_update(upd)
                        if event is not None:
                            await self._queue.put(event)
            except FloodWaitError as exc:
                await asyncio.sleep(exc.seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.0)

    def _normalize_update(self, upd: dict[str, Any]) -> UpdateEvent | None:
        if "message" in upd:
            return UpdateEvent(
                type=EventType.NEW_MESSAGE,
                message=self._normalize_message(upd["message"]),
                raw=upd,
            )
        if "edited_message" in upd:
            return UpdateEvent(
                type=EventType.EDIT_MESSAGE,
                message=self._normalize_message(upd["edited_message"]),
                raw=upd,
            )
        if "channel_post" in upd:
            return UpdateEvent(
                type=EventType.NEW_MESSAGE,
                message=self._normalize_message(upd["channel_post"]),
                raw=upd,
            )
        if "edited_channel_post" in upd:
            return UpdateEvent(
                type=EventType.EDIT_MESSAGE,
                message=self._normalize_message(upd["edited_channel_post"]),
                raw=upd,
            )
        if "callback_query" in upd:
            cb = upd["callback_query"]
            msg_raw = cb.get("message") or {}
            msg = self._normalize_message(msg_raw) if msg_raw else MessageEvent(
                id=0,
                chat=ChatRef(id=int((cb.get("from") or {}).get("id", 0)), type="private"),
                sender=None,
            )
            from_raw = cb.get("from")
            if isinstance(from_raw, dict):
                uid = int(from_raw.get("id", 0))
                msg.sender = UserRef(
                    id=uid,
                    username=from_raw.get("username"),
                    first_name=from_raw.get("first_name"),
                    is_self=self.bot_id is not None and uid == self.bot_id,
                )
            msg.callback_id = str(cb.get("id", ""))
            msg.callback_data = cb.get("data")
            if msg.callback_data is not None:
                msg.text = msg.callback_data
            msg.raw = cb
            return UpdateEvent(type=EventType.CALLBACK_QUERY, message=msg, raw=upd)
        return UpdateEvent(type=EventType.RAW, message=None, raw=upd)

    def _normalize_message(self, msg: dict[str, Any]) -> MessageEvent:
        chat_raw = msg.get("chat") or {}
        chat = ChatRef(
            id=int(chat_raw.get("id", 0)),
            type=str(chat_raw.get("type", "private")),
            title=chat_raw.get("title") or chat_raw.get("username"),
        )
        from_raw = msg.get("from")
        sender: UserRef | None = None
        if isinstance(from_raw, dict):
            uid = int(from_raw.get("id", 0))
            sender = UserRef(
                id=uid,
                username=from_raw.get("username"),
                first_name=from_raw.get("first_name"),
                is_self=self.bot_id is not None and uid == self.bot_id,
            )

        media = self._extract_media(msg)
        reply_raw = msg.get("reply_to_message")
        reply_to_id = int(reply_raw["message_id"]) if isinstance(reply_raw, dict) and "message_id" in reply_raw else None
        ts = msg.get("date")
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts is not None else datetime.now(timezone.utc)

        return MessageEvent(
            id=int(msg.get("message_id", 0)),
            chat=chat,
            sender=sender,
            text=msg.get("text") or msg.get("caption") or "",
            media=media,
            reply_to_id=reply_to_id,
            is_outgoing=sender.is_self if sender is not None else False,
            date=dt,
            raw=msg,
        )

    @staticmethod
    def _extract_media(msg: dict[str, Any]) -> MediaRef | None:
        if "photo" in msg and msg["photo"]:
            largest = msg["photo"][-1]
            return MediaRef(
                media_type="photo",
                file_id=largest.get("file_id"),
                file_size=largest.get("file_size"),
            )
        for key in ("video", "document", "voice", "audio", "sticker", "animation"):
            item = msg.get(key)
            if isinstance(item, dict):
                return MediaRef(
                    media_type="video" if key == "animation" else key,
                    file_id=item.get("file_id"),
                    mime_type=item.get("mime_type"),
                    file_name=item.get("file_name"),
                    file_size=item.get("file_size"),
                )
        return None

    @staticmethod
    def _map_parse_mode(parse_mode: str | None) -> str | None:
        if not parse_mode:
            return None
        return _PARSE_MODE_MAP.get(parse_mode.lower(), parse_mode)

    async def invoke(self, method: str, **params: Any) -> Any:
        return await self._call(method, params)

    async def listen(self) -> AsyncIterator[UpdateEvent]:
        while True:
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
        reply_markup: dict[str, Any] | None = None,
    ) -> MessageEvent:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        pm = self._map_parse_mode(parse_mode)
        if pm:
            payload["parse_mode"] = pm
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        res = await self._call("sendMessage", payload)
        return self._normalize_message(res)

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str = "",
        *,
        parse_mode: str | None = "html",
        reply_markup: dict[str, Any] | None = None,
        rich_message: dict[str, Any] | None = None,
    ) -> MessageEvent:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if rich_message is not None:
            payload["rich_message"] = rich_message
        else:
            payload["text"] = text
            pm = self._map_parse_mode(parse_mode)
            if pm:
                payload["parse_mode"] = pm
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        res = await self._call("editMessageText", payload)
        return self._normalize_message(res)

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        if not message_ids:
            return 0
        try:
            await self._call("deleteMessages", {"chat_id": chat_id, "message_ids": message_ids})
            return len(message_ids)
        except AdapterError:
            deleted = 0
            for mid in message_ids:
                await self._call("deleteMessage", {"chat_id": chat_id, "message_id": mid})
                deleted += 1
            return deleted

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
        del progress
        payload: dict[str, Any] = {"chat_id": chat_id}
        if caption is not None:
            payload["caption"] = caption
        pm = self._map_parse_mode(parse_mode)
        if pm:
            payload["parse_mode"] = pm
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}

        if isinstance(media, bytes):
            files = {"document": ("file.bin", media, "application/octet-stream")}
            res = await self._call("sendDocument", payload, files=files, timeout=120.0)
            return self._normalize_message(res)

        path_str = str(media)
        p = Path(path_str)
        if p.exists() and p.is_file():
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if mime.startswith("image/"):
                method, field = "sendPhoto", "photo"
            elif mime.startswith("video/"):
                method, field = "sendVideo", "video"
            elif mime.startswith("audio/"):
                method, field = "sendAudio", "audio"
            else:
                method, field = "sendDocument", "document"
            files = {field: (p.name, p.read_bytes(), mime)}
            res = await self._call(method, payload, files=files, timeout=120.0)
            return self._normalize_message(res)

        payload["document"] = path_str
        res = await self._call("sendDocument", payload, timeout=120.0)
        return self._normalize_message(res)

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        if not media_items:
            return []

        pm = self._map_parse_mode(parse_mode)
        input_media: list[dict[str, Any]] = []
        files: dict[str, tuple[str, bytes, str]] = {}

        for idx, item in enumerate(media_items):
            entry: dict[str, Any] = {"type": "document"}
            if idx == 0 and caption is not None:
                entry["caption"] = caption
                if pm:
                    entry["parse_mode"] = pm

            if isinstance(item, bytes):
                key = f"file_{idx}"
                files[key] = (f"file_{idx}.bin", item, "application/octet-stream")
                entry["media"] = f"attach://{key}"
            else:
                p = Path(str(item))
                if p.exists() and p.is_file():
                    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    if mime.startswith("image/"):
                        entry["type"] = "photo"
                    elif mime.startswith("video/"):
                        entry["type"] = "video"
                    elif mime.startswith("audio/"):
                        entry["type"] = "audio"
                    key = f"file_{idx}"
                    files[key] = (p.name, p.read_bytes(), mime)
                    entry["media"] = f"attach://{key}"
                else:
                    entry["media"] = str(item)
            input_media.append(entry)

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "media": input_media,
        }
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}

        res = await self._call("sendMediaGroup", payload, files=files or None, timeout=120.0)
        return [self._normalize_message(m) for m in (res or [])]

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        del progress
        if message.media is None or not message.media.file_id:
            raise AdapterError("Message has no downloadable Bot API file_id")

        file_info = await self._call("getFile", {"file_id": message.media.file_id})
        remote_path = file_info.get("file_path")
        if not remote_path:
            raise AdapterError("Bot API getFile did not return file_path")

        def _download_sync() -> bytes:
            conn = self._new_connection(120.0)
            try:
                conn.request("GET", f"{self._file_path}/{remote_path}")
                resp = conn.getresponse()
                if resp.status != 200:
                    raise AdapterError(f"Failed to download file: HTTP {resp.status}")
                return resp.read()
            finally:
                conn.close()

        data = await asyncio.to_thread(_download_sync)
        if destination is None:
            return data
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None:
        reaction = [{"type": "emoji", "emoji": emoji}] if emoji else []
        await self._call(
            "setMessageReaction",
            {"chat_id": chat_id, "message_id": message_id, "reaction": reaction},
        )

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None:
        act = str(action)
        if act == ChatAction.CANCEL:
            return
        await self._call("sendChatAction", {"chat_id": chat_id, "action": act})

    async def pin_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        silent: bool = True,
    ) -> None:
        await self._call(
            "pinChatMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": silent,
            },
        )

    async def ban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "user_id": user_id}
        if until_date is not None:
            payload["until_date"] = until_date
        await self._call("banChatMember", payload)

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        await self._call("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def mute_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "user_id": user_id,
            "permissions": {
                "can_send_messages": False,
                "can_send_audios": False,
                "can_send_documents": False,
                "can_send_photos": False,
                "can_send_videos": False,
                "can_send_video_notes": False,
                "can_send_voice_notes": False,
                "can_send_polls": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False,
            },
        }
        if until_date is not None:
            payload["until_date"] = until_date
        await self._call("restrictChatMember", payload)

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        await self._call("banChatMember", {"chat_id": chat_id, "user_id": user_id})
        await self._call("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        res = await self._call("getChat", {"chat_id": chat_id})
        return ChatRef(
            id=int(res.get("id", 0)),
            type=str(res.get("type", "private")),
            title=res.get("title") or res.get("username"),
        )

    async def answer_callback(
        self,
        callback_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "callback_query_id": callback_id,
            "show_alert": show_alert,
        }
        if text is not None:
            payload["text"] = text
        if url is not None:
            payload["url"] = url
        if cache_time is not None:
            payload["cache_time"] = cache_time
        await self._call("answerCallbackQuery", payload)

    async def send_ephemeral_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        receiver_user_id: int | None = None,
        callback_query_id: str | None = None,
        replace_callback_query_message: bool = False,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
        reply_markup: dict[str, Any] | None = None,
    ) -> MessageEvent:
        """Send a Bot API 10.2+ ephemeral message visible only to a specific user."""
        ephemeral_params: dict[str, Any] = {}
        if receiver_user_id is not None:
            ephemeral_params["receiver_user_id"] = int(receiver_user_id)
        if callback_query_id is not None:
            ephemeral_params["callback_query_id"] = str(callback_query_id)
        if replace_callback_query_message:
            ephemeral_params["replace_callback_query_message"] = True
        if not ephemeral_params:
            raise ValueError(
                "Either receiver_user_id or callback_query_id must be provided for ephemeral messages."
            )

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "ephemeral_message_parameters": ephemeral_params,
        }
        pm = self._map_parse_mode(parse_mode)
        if pm:
            payload["parse_mode"] = pm
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        res = await self._call("sendMessage", payload)
        return self._normalize_message(res)

    async def edit_ephemeral_message(
        self,
        chat_id: int | str,
        ephemeral_message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
        reply_markup: dict[str, Any] | None = None,
    ) -> MessageEvent:
        """Edit an existing Bot API 10.2+ ephemeral message."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "ephemeral_message_id": int(ephemeral_message_id),
            "text": text,
        }
        pm = self._map_parse_mode(parse_mode)
        if pm:
            payload["parse_mode"] = pm
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        res = await self._call("editEphemeralMessageText", payload)
        return self._normalize_message(res)

    async def delete_ephemeral_message(
        self,
        chat_id: int | str,
        ephemeral_message_id: int,
    ) -> bool:
        """Delete a Bot API 10.2+ ephemeral message."""
        res = await self._call(
            "deleteEphemeralMessage",
            {"chat_id": chat_id, "ephemeral_message_id": int(ephemeral_message_id)},
        )
        return bool(res)

    async def send_message_draft(
        self,
        chat_id: int | str,
        draft_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        parse_mode: str | None = "html",
        can_stop: bool = False,
        keep_on_stop: bool = False,
    ) -> bool:
        """Stream a partial message draft (Bot API 9.3 / 9.5 / 10.3)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": int(draft_id),
            "text": text,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = int(message_thread_id)
        pm = self._map_parse_mode(parse_mode)
        if pm:
            payload["parse_mode"] = pm
        if can_stop:
            payload["can_stop"] = True
        if keep_on_stop:
            payload["keep_on_stop"] = True
        res = await self._call("sendMessageDraft", payload)
        return bool(res)

    async def set_chat_member_tag(
        self,
        chat_id: int | str,
        user_id: int | str,
        tag: str | None = None,
    ) -> bool:
        """Set or clear a member's text tag in a group (Bot API 9.5+)."""
        payload: dict[str, Any] = {"chat_id": chat_id, "user_id": user_id}
        if tag is not None:
            payload["tag"] = tag
        res = await self._call("setChatMemberTag", payload)
        return bool(res)

    async def create_forum_topic(
        self,
        chat_id: int | str,
        name: str,
        *,
        icon_color: int | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a forum topic in a supergroup or private chat (Bot API 9.4+)."""
        payload: dict[str, Any] = {"chat_id": chat_id, "name": name}
        if icon_color is not None:
            payload["icon_color"] = int(icon_color)
        if icon_custom_emoji_id is not None:
            payload["icon_custom_emoji_id"] = str(icon_custom_emoji_id)
        res = await self._call("createForumTopic", payload)
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def edit_forum_topic(
        self,
        chat_id: int | str,
        message_thread_id: int,
        *,
        name: str | None = None,
        icon_custom_emoji_id: str | None = None,
    ) -> bool:
        """Edit a forum topic's name or icon."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_thread_id": int(message_thread_id),
        }
        if name is not None:
            payload["name"] = name
        if icon_custom_emoji_id is not None:
            payload["icon_custom_emoji_id"] = str(icon_custom_emoji_id)
        return bool(await self._call("editForumTopic", payload))

    async def close_forum_topic(self, chat_id: int | str, message_thread_id: int) -> bool:
        """Close an open forum topic."""
        return bool(
            await self._call(
                "closeForumTopic",
                {"chat_id": chat_id, "message_thread_id": int(message_thread_id)},
            )
        )

    async def reopen_forum_topic(self, chat_id: int | str, message_thread_id: int) -> bool:
        """Reopen a closed forum topic."""
        return bool(
            await self._call(
                "reopenForumTopic",
                {"chat_id": chat_id, "message_thread_id": int(message_thread_id)},
            )
        )

    async def delete_forum_topic(self, chat_id: int | str, message_thread_id: int) -> bool:
        """Delete a forum topic along with all its messages."""
        return bool(
            await self._call(
                "deleteForumTopic",
                {"chat_id": chat_id, "message_thread_id": int(message_thread_id)},
            )
        )

    async def unpin_all_forum_topic_messages(
        self,
        chat_id: int | str,
        message_thread_id: int,
    ) -> bool:
        """Clear the list of pinned messages in a forum topic."""
        return bool(
            await self._call(
                "unpinAllForumTopicMessages",
                {"chat_id": chat_id, "message_thread_id": int(message_thread_id)},
            )
        )

    async def get_forum_topic_icon_stickers(self) -> list[dict[str, Any]]:
        """Get custom emoji stickers usable as forum topic icons."""
        res = await self._call("getForumTopicIconStickers", {})
        return list(res) if isinstance(res, list) else []

    # ── Gifts (Bot API 8.0+) ────────────────────────────────────────

    async def get_available_gifts(self) -> list[dict[str, Any]]:
        """Return the list of gifts that can be sent by the bot."""
        res = await self._call("getAvailableGifts", {})
        if isinstance(res, dict) and isinstance(res.get("gifts"), list):
            return list(res["gifts"])
        return list(res) if isinstance(res, list) else []

    async def send_gift(
        self,
        gift_id: str,
        *,
        user_id: int | None = None,
        chat_id: int | str | None = None,
        pay_for_upgrade: bool | None = None,
        text: str | None = None,
        text_parse_mode: str | None = None,
        text_entities: Sequence[dict[str, Any]] | None = None,
    ) -> bool:
        """Send a gift to a user or channel chat."""
        if user_id is None and chat_id is None:
            raise ValueError("Either user_id or chat_id must be provided.")
        payload: dict[str, Any] = {"gift_id": str(gift_id)}
        if user_id is not None:
            payload["user_id"] = int(user_id)
        if chat_id is not None:
            payload["chat_id"] = chat_id
        if pay_for_upgrade is not None:
            payload["pay_for_upgrade"] = bool(pay_for_upgrade)
        if text is not None:
            payload["text"] = text
        if text_parse_mode is not None:
            payload["text_parse_mode"] = text_parse_mode
        if text_entities is not None:
            payload["text_entities"] = list(text_entities)
        return bool(await self._call("sendGift", payload))

    async def gift_premium_subscription(
        self,
        user_id: int,
        month_count: int,
        star_count: int,
        *,
        text: str | None = None,
        text_parse_mode: str | None = None,
        text_entities: Sequence[dict[str, Any]] | None = None,
    ) -> bool:
        """Gift a Telegram Premium subscription to a user using Stars."""
        payload: dict[str, Any] = {
            "user_id": int(user_id),
            "month_count": int(month_count),
            "star_count": int(star_count),
        }
        if text is not None:
            payload["text"] = text
        if text_parse_mode is not None:
            payload["text_parse_mode"] = text_parse_mode
        if text_entities is not None:
            payload["text_entities"] = list(text_entities)
        return bool(await self._call("giftPremiumSubscription", payload))

    # ── Stories (Business Stories, Bot API 9.0+) ────────────────────

    async def post_story(
        self,
        business_connection_id: str,
        content: dict[str, Any],
        active_period: int,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        caption_entities: Sequence[dict[str, Any]] | None = None,
        areas: Sequence[dict[str, Any]] | None = None,
        post_to_chat_page: bool | None = None,
        protect_content: bool | None = None,
    ) -> dict[str, Any]:
        """Post a story on behalf of a managed business account."""
        payload: dict[str, Any] = {
            "business_connection_id": str(business_connection_id),
            "content": dict(content),
            "active_period": int(active_period),
        }
        if caption is not None:
            payload["caption"] = caption
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if caption_entities is not None:
            payload["caption_entities"] = list(caption_entities)
        if areas is not None:
            payload["areas"] = list(areas)
        if post_to_chat_page is not None:
            payload["post_to_chat_page"] = bool(post_to_chat_page)
        if protect_content is not None:
            payload["protect_content"] = bool(protect_content)
        res = await self._call("postStory", payload)
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def edit_story(
        self,
        business_connection_id: str,
        story_id: int,
        content: dict[str, Any],
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        caption_entities: Sequence[dict[str, Any]] | None = None,
        areas: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Edit a previously posted business story."""
        payload: dict[str, Any] = {
            "business_connection_id": str(business_connection_id),
            "story_id": int(story_id),
            "content": dict(content),
        }
        if caption is not None:
            payload["caption"] = caption
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if caption_entities is not None:
            payload["caption_entities"] = list(caption_entities)
        if areas is not None:
            payload["areas"] = list(areas)
        res = await self._call("editStory", payload)
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def delete_story(self, business_connection_id: str, story_id: int) -> bool:
        """Delete a story previously posted by the bot on behalf of a business account."""
        return bool(
            await self._call(
                "deleteStory",
                {
                    "business_connection_id": str(business_connection_id),
                    "story_id": int(story_id),
                },
            )
        )

    # ── Business Features (Bot API 7.2+ / 9.0+) ─────────────────────

    async def get_business_connection(self, business_connection_id: str) -> dict[str, Any]:
        """Get information about the connection of the bot with a business account."""
        res = await self._call(
            "getBusinessConnection",
            {"business_connection_id": str(business_connection_id)},
        )
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def read_business_message(
        self,
        business_connection_id: str,
        chat_id: int | str,
        message_id: int,
    ) -> bool:
        """Mark an incoming business message as read."""
        return bool(
            await self._call(
                "readBusinessMessage",
                {
                    "business_connection_id": str(business_connection_id),
                    "chat_id": chat_id,
                    "message_id": int(message_id),
                },
            )
        )

    async def delete_business_messages(
        self,
        business_connection_id: str,
        message_ids: Sequence[int],
    ) -> bool:
        """Delete messages on behalf of a business account."""
        return bool(
            await self._call(
                "deleteBusinessMessages",
                {
                    "business_connection_id": str(business_connection_id),
                    "message_ids": [int(m) for m in message_ids],
                },
            )
        )

    async def set_business_account_name(
        self,
        business_connection_id: str,
        first_name: str,
        *,
        last_name: str | None = None,
    ) -> bool:
        """Change the first and last name of a managed business account."""
        payload: dict[str, Any] = {
            "business_connection_id": str(business_connection_id),
            "first_name": first_name,
        }
        if last_name is not None:
            payload["last_name"] = last_name
        return bool(await self._call("setBusinessAccountName", payload))

    async def set_business_account_username(
        self,
        business_connection_id: str,
        *,
        username: str | None = None,
    ) -> bool:
        """Change the username of a managed business account."""
        payload: dict[str, Any] = {"business_connection_id": str(business_connection_id)}
        if username is not None:
            payload["username"] = username
        return bool(await self._call("setBusinessAccountUsername", payload))

    async def set_business_account_bio(
        self,
        business_connection_id: str,
        *,
        bio: str | None = None,
    ) -> bool:
        """Change the bio of a managed business account."""
        payload: dict[str, Any] = {"business_connection_id": str(business_connection_id)}
        if bio is not None:
            payload["bio"] = bio
        return bool(await self._call("setBusinessAccountBio", payload))

    async def set_business_account_gift_settings(
        self,
        business_connection_id: str,
        show_gift_button: bool,
        accepted_gift_types: dict[str, Any],
    ) -> bool:
        """Change privacy settings pertaining to incoming gifts in a business account."""
        return bool(
            await self._call(
                "setBusinessAccountGiftSettings",
                {
                    "business_connection_id": str(business_connection_id),
                    "show_gift_button": bool(show_gift_button),
                    "accepted_gift_types": dict(accepted_gift_types),
                },
            )
        )

    async def get_business_account_star_balance(
        self,
        business_connection_id: str,
    ) -> dict[str, Any]:
        """Return the amount of Telegram Stars owned by a managed business account."""
        res = await self._call(
            "getBusinessAccountStarBalance",
            {"business_connection_id": str(business_connection_id)},
        )
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def get_business_account_gifts(
        self,
        business_connection_id: str,
        *,
        exclude_unsaved: bool | None = None,
        exclude_saved: bool | None = None,
        exclude_unlimited: bool | None = None,
        exclude_limited: bool | None = None,
        exclude_unique: bool | None = None,
        sort_by_price: bool | None = None,
        offset: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return the gifts received and owned by a managed business account."""
        payload: dict[str, Any] = {"business_connection_id": str(business_connection_id)}
        for key, val in (
            ("exclude_unsaved", exclude_unsaved),
            ("exclude_saved", exclude_saved),
            ("exclude_unlimited", exclude_unlimited),
            ("exclude_limited", exclude_limited),
            ("exclude_unique", exclude_unique),
            ("sort_by_price", sort_by_price),
        ):
            if val is not None:
                payload[key] = bool(val)
        if offset is not None:
            payload["offset"] = str(offset)
        if limit is not None:
            payload["limit"] = int(limit)
        res = await self._call("getBusinessAccountGifts", payload)
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def convert_gift_to_stars(
        self,
        business_connection_id: str,
        owned_gift_id: str,
    ) -> bool:
        """Convert a regular gift owned by a business account to Telegram Stars."""
        return bool(
            await self._call(
                "convertGiftToStars",
                {
                    "business_connection_id": str(business_connection_id),
                    "owned_gift_id": str(owned_gift_id),
                },
            )
        )

    async def upgrade_gift(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        *,
        keep_original_details: bool | None = None,
        star_count: int | None = None,
    ) -> bool:
        """Upgrade a regular gift owned by a business account to a unique gift."""
        payload: dict[str, Any] = {
            "business_connection_id": str(business_connection_id),
            "owned_gift_id": str(owned_gift_id),
        }
        if keep_original_details is not None:
            payload["keep_original_details"] = bool(keep_original_details)
        if star_count is not None:
            payload["star_count"] = int(star_count)
        return bool(await self._call("upgradeGift", payload))

    async def transfer_gift(
        self,
        business_connection_id: str,
        owned_gift_id: str,
        new_owner_chat_id: int,
        *,
        star_count: int | None = None,
    ) -> bool:
        """Transfer an owned unique gift to another user."""
        payload: dict[str, Any] = {
            "business_connection_id": str(business_connection_id),
            "owned_gift_id": str(owned_gift_id),
            "new_owner_chat_id": int(new_owner_chat_id),
        }
        if star_count is not None:
            payload["star_count"] = int(star_count)
        return bool(await self._call("transferGift", payload))

    async def set_my_settings(
        self,
        *,
        can_join_groups: bool | None = None,
        can_read_all_group_messages: bool | None = None,
        is_inline: bool | None = None,
        inline_query_placeholder: str | None = None,
        needs_inline_query_location: bool | None = None,
        has_topics_enabled: bool | None = None,
        has_topic_sidebar: bool | None = None,
        callback_query_mode: str | None = None,
        **extra: Any,
    ) -> bool:
        """Update bot settings via Bot API 10.5+ setMySettings."""
        payload: dict[str, Any] = dict(extra)
        for key, val in (
            ("can_join_groups", can_join_groups),
            ("can_read_all_group_messages", can_read_all_group_messages),
            ("is_inline", is_inline),
            ("needs_inline_query_location", needs_inline_query_location),
            ("has_topics_enabled", has_topics_enabled),
            ("has_topic_sidebar", has_topic_sidebar),
        ):
            if val is not None:
                payload[key] = bool(val)
        if inline_query_placeholder is not None:
            payload["inline_query_placeholder"] = str(inline_query_placeholder)
        if callback_query_mode is not None:
            payload["callback_query_mode"] = str(callback_query_mode)
        res = await self._call("setMySettings", payload)
        return bool(res)

    async def set_webhook(
        self,
        url: str,
        *,
        secret_token: str | None = None,
        drop_pending_updates: bool = False,
        allowed_updates: Sequence[str] | None = None,
        max_connections: int | None = None,
    ) -> bool:
        """Configure Telegram Bot API webhook endpoint."""
        payload: dict[str, Any] = {
            "url": url,
            "allowed_updates": list(allowed_updates or self._allowed_updates),
        }
        if secret_token is not None:
            payload["secret_token"] = secret_token
        if drop_pending_updates:
            payload["drop_pending_updates"] = True
        if max_connections is not None:
            payload["max_connections"] = int(max_connections)
        res = await self._call("setWebhook", payload)
        return bool(res)

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> bool:
        """Remove the configured Telegram Bot API webhook."""
        payload: dict[str, Any] = {}
        if drop_pending_updates:
            payload["drop_pending_updates"] = True
        res = await self._call("deleteWebhook", payload)
        return bool(res)

    @staticmethod
    def _resolve_rich_payload(
        rich_msg: dict[str, Any] | None,
        *,
        html: str | None,
        markdown: str | None,
        blocks: Sequence[dict[str, Any]] | None,
        media: Sequence[dict[str, Any]] | None = None,
        is_rtl: bool | None = None,
        skip_entity_detection: bool | None = None,
    ) -> dict[str, Any]:
        if rich_msg is not None:
            return dict(rich_msg)
        return rich_message(
            html=html,
            markdown=markdown,
            blocks=blocks,
            media=media,
            is_rtl=is_rtl,
            skip_entity_detection=skip_entity_detection,
        )

    async def send_rich_message(
        self,
        chat_id: int | str,
        rich_msg: dict[str, Any] | None = None,
        *,
        html: str | None = None,
        markdown: str | None = None,
        blocks: Sequence[dict[str, Any]] | None = None,
        media: Sequence[dict[str, Any]] | None = None,
        is_rtl: bool | None = None,
        skip_entity_detection: bool | None = None,
        reply_to: int | None = None,
        reply_markup: dict[str, Any] | None = None,
        ephemeral_message_parameters: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        disable_notification: bool = False,
        protect_content: bool = False,
    ) -> MessageEvent:
        """Send a structured Bot API 10.1+ Rich Message."""
        rm_obj = self._resolve_rich_payload(
            rich_msg,
            html=html,
            markdown=markdown,
            blocks=blocks,
            media=media,
            is_rtl=is_rtl,
            skip_entity_detection=skip_entity_detection,
        )
        payload: dict[str, Any] = {"chat_id": chat_id, "rich_message": rm_obj}
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if ephemeral_message_parameters is not None:
            payload["ephemeral_message_parameters"] = ephemeral_message_parameters
        if message_thread_id is not None:
            payload["message_thread_id"] = int(message_thread_id)
        if disable_notification:
            payload["disable_notification"] = True
        if protect_content:
            payload["protect_content"] = True
        res = await self._call("sendRichMessage", payload)
        return self._normalize_message(res)

    async def send_rich_message_draft(
        self,
        chat_id: int | str,
        draft_id: int,
        rich_msg: dict[str, Any] | None = None,
        *,
        html: str | None = None,
        markdown: str | None = None,
        blocks: Sequence[dict[str, Any]] | None = None,
        is_rtl: bool | None = None,
        message_thread_id: int | None = None,
        can_stop: bool = False,
        keep_on_stop: bool = False,
    ) -> bool:
        """Stream a partial Bot API 10.1+ Rich Message draft."""
        rm_obj = self._resolve_rich_payload(
            rich_msg,
            html=html,
            markdown=markdown,
            blocks=blocks,
            is_rtl=is_rtl,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": int(draft_id),
            "rich_message": rm_obj,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = int(message_thread_id)
        if can_stop:
            payload["can_stop"] = True
        if keep_on_stop:
            payload["keep_on_stop"] = True
        res = await self._call("sendRichMessageDraft", payload)
        return bool(res)

    def create_webhook_server(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        path: str = "/webhook",
        secret_token: str | None = None,
    ) -> WebhookServer:
        """Create a zero-dependency asyncio WebhookServer bound to this adapter."""
        return WebhookServer(
            self,
            host=host,
            port=port,
            path=path,
            secret_token=secret_token,
        )


class WebhookServer:
    """Zero-dependency asyncio HTTP/1.1 webhook server for BotAPIAdapter."""

    def __init__(
        self,
        adapter: BotAPIAdapter,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        path: str = "/webhook",
        secret_token: str | None = None,
        max_body_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.adapter = adapter
        self.host = host
        self.port = int(port)
        self.path = "/" + path.lstrip("/")
        self.secret_token = secret_token
        self.max_body_bytes = max_body_bytes
        self._server: asyncio.AbstractServer | None = None

    @property
    def bound_port(self) -> int:
        if self._server and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self.port

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        body = _json_dumps(payload)
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(head + body)
        await writer.drain()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10.0)
        except Exception:
            writer.close()
            return

        try:
            header_text = raw_head.decode("latin-1")
            lines = header_text.split("\r\n")
            request_line = lines[0].split()
            if len(request_line) < 2:
                await self._write_response(writer, 400, "Bad Request", {"ok": False, "error": "malformed request"})
                return
            method, req_target = request_line[0].upper(), request_line[1].split("?", 1)[0]

            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if req_target == "/health" and method == "GET":
                await self._write_response(writer, 200, "OK", {"ok": True, "status": "healthy"})
                return

            if req_target != self.path:
                await self._write_response(writer, 404, "Not Found", {"ok": False, "error": "not found"})
                return

            if method != "POST":
                await self._write_response(writer, 405, "Method Not Allowed", {"ok": False, "error": "method not allowed"})
                return

            if self.secret_token is not None:
                got_secret = headers.get("x-telegram-bot-api-secret-token")
                if got_secret != self.secret_token:
                    await self._write_response(writer, 403, "Forbidden", {"ok": False, "error": "invalid secret token"})
                    return

            content_length = int(headers.get("content-length", "0"))
            if content_length < 0 or content_length > self.max_body_bytes:
                await self._write_response(writer, 413, "Payload Too Large", {"ok": False, "error": "payload too large"})
                return

            body = await asyncio.wait_for(reader.readexactly(content_length), timeout=10.0) if content_length else b"{}"
            update = _json_loads(body)
            if not isinstance(update, dict):
                await self._write_response(writer, 400, "Bad Request", {"ok": False, "error": "expected json object"})
                return

            event = self.adapter._normalize_update(update)
            if event is not None:
                await self.adapter._queue.put(event)
            await self._write_response(writer, 200, "OK", {"ok": True})
        except Exception as exc:
            try:
                await self._write_response(writer, 400, "Bad Request", {"ok": False, "error": str(exc)})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
