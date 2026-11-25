from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import ChatAction, ChatRef, MessageEvent
from shirdal.engine.fsm import FSMContext, FSMStorage, MemoryStorage
from shirdal.engine.media import ProgressCallback, ProgressTracker


class Context:
    """Ergonomic, context-first wrapper around an incoming or sent MessageEvent."""

    __slots__ = (
        "message",
        "adapter",
        "state",
        "command",
        "args",
        "arg_str",
        "match",
        "_task_pool",
    )

    def __init__(
        self,
        message: MessageEvent,
        adapter: TransportAdapter,
        *,
        task_pool: set[asyncio.Task[Any]] | None = None,
        storage: FSMStorage | None = None,
    ) -> None:
        self.message = message
        self.adapter = adapter
        fsm_storage = storage if storage is not None else MemoryStorage()
        sender_id = message.sender.id if message.sender else 0
        self.state = FSMContext(fsm_storage, (message.chat.id, sender_id))
        self.command: str | None = None
        self.args: list[str] = []
        self.arg_str: str = ""
        self.match: re.Match[str] | None = None
        self._task_pool = task_pool

    @property
    def id(self) -> int:
        return self.message.id

    @property
    def chat_id(self) -> int:
        return self.message.chat.id

    @property
    def sender_id(self) -> int | None:
        return self.message.sender.id if self.message.sender else None

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def is_outgoing(self) -> bool:
        return self.message.is_outgoing

    @property
    def has_media(self) -> bool:
        return self.message.media is not None

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        if self._task_pool is not None:
            self._task_pool.add(task)
            task.add_done_callback(self._task_pool.discard)
        return task

    def _schedule_delete(self, message_id: int, delay: float, revoke: bool = True) -> None:
        async def _worker() -> None:
            await asyncio.sleep(delay)
            await self.adapter.delete_messages(self.chat_id, [message_id], revoke=revoke)

        self._spawn(_worker())

    async def reply(
        self,
        text: str,
        *,
        auto_delete: float | None = None,
        parse_mode: str | None = "html",
    ) -> Context:
        sent = await self.adapter.send_message(
            self.chat_id,
            text,
            reply_to=self.message.id,
            parse_mode=parse_mode,
        )
        if auto_delete is not None and auto_delete >= 0:
            self._schedule_delete(sent.id, auto_delete)
        return Context(
            sent,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    async def send(
        self,
        text: str,
        *,
        auto_delete: float | None = None,
        parse_mode: str | None = "html",
    ) -> Context:
        sent = await self.adapter.send_message(
            self.chat_id,
            text,
            reply_to=None,
            parse_mode=parse_mode,
        )
        if auto_delete is not None and auto_delete >= 0:
            self._schedule_delete(sent.id, auto_delete)
        return Context(
            sent,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    async def edit(
        self,
        text: str,
        *,
        auto_delete: float | None = None,
        parse_mode: str | None = "html",
    ) -> Context:
        edited = await self.adapter.edit_message(
            self.chat_id,
            self.message.id,
            text,
            parse_mode=parse_mode,
        )
        if auto_delete is not None and auto_delete >= 0:
            self._schedule_delete(edited.id, auto_delete)
        return Context(
            edited,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    async def delete(self, *, revoke: bool = True) -> int:
        return await self.adapter.delete_messages(
            self.chat_id, [self.message.id], revoke=revoke
        )

    def delete_after(self, delay: float, *, revoke: bool = True) -> None:
        self._schedule_delete(self.message.id, delay, revoke=revoke)

    async def reply_media(
        self,
        media: str | Path | bytes,
        *,
        caption: str | None = None,
        auto_delete: float | None = None,
        parse_mode: str | None = "html",
        progress: ProgressCallback | None = None,
        progress_interval: float = 1.5,
    ) -> Context:
        tracker = (
            ProgressTracker(progress, min_interval=progress_interval).report
            if progress is not None
            else None
        )
        sent = await self.adapter.send_media(
            self.chat_id,
            media,
            caption=caption,
            reply_to=self.message.id,
            parse_mode=parse_mode,
            progress=tracker,
        )
        if auto_delete is not None and auto_delete >= 0:
            self._schedule_delete(sent.id, auto_delete)
        return Context(
            sent,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    async def reply_album(
        self,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        parse_mode: str | None = "html",
    ) -> list[Context]:
        sent_list = await self.adapter.send_album(
            self.chat_id,
            media_items,
            caption=caption,
            reply_to=self.message.id,
            parse_mode=parse_mode,
        )
        return [
            Context(
                m,
                self.adapter,
                task_pool=self._task_pool,
                storage=self.state.storage,
            )
            for m in sent_list
        ]

    async def download(
        self,
        destination: str | Path | None = None,
        *,
        progress: ProgressCallback | None = None,
        progress_interval: float = 1.5,
    ) -> Path | bytes:
        tracker = (
            ProgressTracker(progress, min_interval=progress_interval).report
            if progress is not None
            else None
        )
        return await self.adapter.download_media(
            self.message, destination=destination, progress=tracker
        )

    async def react(self, emoji: str | None) -> None:
        await self.adapter.send_reaction(self.chat_id, self.message.id, emoji)

    async def pin(self, *, silent: bool = True) -> None:
        await self.adapter.pin_message(self.chat_id, self.message.id, silent=silent)

    async def ban(
        self, user_id: int | str | None = None, *, until_date: int | None = None
    ) -> None:
        target = user_id if user_id is not None else self.sender_id
        if target is None:
            raise ValueError("user_id is required when message has no sender")
        await self.adapter.ban_user(self.chat_id, target, until_date=until_date)

    async def unban(self, user_id: int | str | None = None) -> None:
        target = user_id if user_id is not None else self.sender_id
        if target is None:
            raise ValueError("user_id is required when message has no sender")
        await self.adapter.unban_user(self.chat_id, target)

    async def mute(
        self, user_id: int | str | None = None, *, until_date: int | None = None
    ) -> None:
        target = user_id if user_id is not None else self.sender_id
        if target is None:
            raise ValueError("user_id is required when message has no sender")
        await self.adapter.mute_user(self.chat_id, target, until_date=until_date)

    async def kick(self, user_id: int | str | None = None) -> None:
        target = user_id if user_id is not None else self.sender_id
        if target is None:
            raise ValueError("user_id is required when message has no sender")
        await self.adapter.kick_user(self.chat_id, target)

    async def get_chat(
        self, chat_id: int | None = None, *, ttl: float = 300.0
    ) -> ChatRef:
        target_id = chat_id if chat_id is not None else self.chat_id
        storage = self.state.storage
        get_cached = getattr(storage, "get_chat", None)
        set_cached = getattr(storage, "set_chat", None)

        if callable(get_cached):
            cached = await get_cached(target_id)
            if cached is not None:
                return ChatRef(
                    id=cached.chat_id,
                    type=cached.chat_type,
                    title=cached.title,
                )

        chat = await self.adapter.get_chat(target_id)
        if callable(set_cached):
            await set_cached(
                chat.id,
                chat_type=chat.type,
                title=chat.title,
                ttl=ttl,
            )
        return chat

    @asynccontextmanager
    async def typing(
        self, action: ChatAction | str = ChatAction.TYPING, *, interval: float = 4.0
    ) -> AsyncIterator[None]:
        stop_flag = False

        async def _keep_alive() -> None:
            while not stop_flag:
                await self.adapter.send_chat_action(self.chat_id, action)
                await asyncio.sleep(interval)

        task = asyncio.create_task(_keep_alive())
        try:
            yield
        finally:
            stop_flag = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
