from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, TypeVar

from shirdal.core.adapter import FloodWaitError, TransportAdapter
from shirdal.core.events import ChatAction, ChatRef, MessageEvent, UpdateEvent

T = TypeVar("T")


@dataclass(slots=True)
class AntiFloodConfig:
    """Configuration for per-chat pacing and automatic FloodWait recovery."""

    per_chat_interval: float = 0.25
    max_wait_seconds: float = 60.0
    max_retries: int = 3
    safety_buffer: float = 0.05
    max_concurrent: int = 16


@dataclass(slots=True)
class FloodStats:
    total_requests: int = 0
    flood_waits_handled: int = 0
    retries: int = 0
    total_slept_seconds: float = 0.0


class AntiFloodAdapter:
    """Transparent TransportAdapter wrapper providing rate pacing and FloodWait recovery."""

    def __init__(
        self,
        inner: TransportAdapter,
        config: AntiFloodConfig | None = None,
    ) -> None:
        self.inner = inner
        self.config = config or AntiFloodConfig()
        self.stats = FloodStats()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._chat_locks: dict[int | str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_chat_call: dict[int | str, float] = {}
        self._global_cooldown_until: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self.inner.is_connected

    async def connect(self) -> None:
        await self.inner.connect()

    async def disconnect(self) -> None:
        await self.inner.disconnect()

    def listen(self) -> AsyncIterator[UpdateEvent]:
        return self.inner.listen()

    async def _wait_global_cooldown(self) -> None:
        now = time.monotonic()
        if self._global_cooldown_until > now:
            delay = self._global_cooldown_until - now
            self.stats.total_slept_seconds += delay
            await asyncio.sleep(delay)

    async def _pace_chat(self, chat_id: int | str | None) -> None:
        if chat_id is None or self.config.per_chat_interval <= 0:
            return
        now = time.monotonic()
        last = self._last_chat_call.get(chat_id)
        if last is not None:
            elapsed = now - last
            if elapsed < self.config.per_chat_interval:
                delay = self.config.per_chat_interval - elapsed
                self.stats.total_slept_seconds += delay
                await asyncio.sleep(delay)
        self._last_chat_call[chat_id] = time.monotonic()

    async def _execute(
        self,
        chat_id: int | str | None,
        call: Callable[[], Awaitable[T]],
    ) -> T:
        lock = self._chat_locks[chat_id] if chat_id is not None else None

        for attempt in range(self.config.max_retries + 1):
            async with self._semaphore:
                if lock is not None:
                    async with lock:
                        await self._wait_global_cooldown()
                        await self._pace_chat(chat_id)
                        try:
                            self.stats.total_requests += 1
                            return await call()
                        except FloodWaitError as exc:
                            if (
                                exc.seconds > self.config.max_wait_seconds
                                or attempt >= self.config.max_retries
                            ):
                                raise
                            wait_time = exc.seconds + self.config.safety_buffer
                            self._global_cooldown_until = max(
                                self._global_cooldown_until,
                                time.monotonic() + wait_time,
                            )
                            self.stats.flood_waits_handled += 1
                            self.stats.retries += 1
                            self.stats.total_slept_seconds += wait_time
                            await asyncio.sleep(wait_time)
                else:
                    await self._wait_global_cooldown()
                    try:
                        self.stats.total_requests += 1
                        return await call()
                    except FloodWaitError as exc:
                        if (
                            exc.seconds > self.config.max_wait_seconds
                            or attempt >= self.config.max_retries
                        ):
                            raise
                        wait_time = exc.seconds + self.config.safety_buffer
                        self._global_cooldown_until = max(
                            self._global_cooldown_until,
                            time.monotonic() + wait_time,
                        )
                        self.stats.flood_waits_handled += 1
                        self.stats.retries += 1
                        self.stats.total_slept_seconds += wait_time
                        await asyncio.sleep(wait_time)

        raise RuntimeError("Unreachable retry loop exit")

    async def invoke(self, method: str, **params: Any) -> Any:
        chat_id = params.get("chat_id")
        return await self._execute(chat_id, lambda: self.inner.invoke(method, **params))

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
        **kwargs: Any,
    ) -> MessageEvent:
        return await self._execute(
            chat_id,
            lambda: self.inner.send_message(
                chat_id, text, reply_to=reply_to, parse_mode=parse_mode, **kwargs
            ),
        )

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
        **kwargs: Any,
    ) -> MessageEvent:
        return await self._execute(
            chat_id,
            lambda: self.inner.edit_message(
                chat_id, message_id, text, parse_mode=parse_mode, **kwargs
            ),
        )

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        return await self._execute(
            chat_id,
            lambda: self.inner.delete_messages(chat_id, message_ids, revoke=revoke),
        )

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
        return await self._execute(
            chat_id,
            lambda: self.inner.send_media(
                chat_id,
                media,
                caption=caption,
                reply_to=reply_to,
                parse_mode=parse_mode,
                progress=progress,
            ),
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
        return await self._execute(
            chat_id,
            lambda: self.inner.send_album(
                chat_id,
                media_items,
                caption=caption,
                reply_to=reply_to,
                parse_mode=parse_mode,
            ),
        )

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        return await self._execute(
            message.chat.id,
            lambda: self.inner.download_media(
                message, destination=destination, progress=progress
            ),
        )

    async def send_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        emoji: str | None,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.send_reaction(chat_id, message_id, emoji),
        )

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: ChatAction | str,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.send_chat_action(chat_id, action),
        )

    async def pin_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        silent: bool = True,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.pin_message(chat_id, message_id, silent=silent),
        )

    async def ban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.ban_user(chat_id, user_id, until_date=until_date),
        )

    async def unban_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.unban_user(chat_id, user_id),
        )

    async def mute_user(
        self,
        chat_id: int | str,
        user_id: int | str,
        *,
        until_date: int | None = None,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.mute_user(chat_id, user_id, until_date=until_date),
        )

    async def kick_user(
        self,
        chat_id: int | str,
        user_id: int | str,
    ) -> None:
        await self._execute(
            chat_id,
            lambda: self.inner.kick_user(chat_id, user_id),
        )

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        return await self._execute(
            chat_id,
            lambda: self.inner.get_chat(chat_id),
        )
