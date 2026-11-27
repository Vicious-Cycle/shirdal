from __future__ import annotations

import asyncio
import itertools
import re
import time
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import ChatAction, ChatRef, MessageEvent
from shirdal.engine.fsm import FSMContext, FSMStorage, FSMStrategy, MemoryStorage, resolve_fsm_key
from shirdal.engine.media import ProgressCallback, ProgressTracker


_DRAFT_COUNTER = itertools.count(1)


class DraftStream:
    """Async context manager for live AI message streaming via Bot API sendMessageDraft."""

    def __init__(
        self,
        ctx: Context,
        *,
        draft_id: int | None = None,
        parse_mode: str | None = "html",
        can_stop: bool = False,
        keep_on_stop: bool = False,
        min_interval: float = 0.25,
        finalize: bool = True,
    ) -> None:
        self._ctx = ctx
        self.draft_id = int(draft_id) if draft_id is not None else next(_DRAFT_COUNTER)
        self.parse_mode = parse_mode
        self.can_stop = can_stop
        self.keep_on_stop = keep_on_stop
        self.min_interval = max(0.0, float(min_interval))
        self.finalize = finalize
        self._buffer: list[str] = []
        self._last_sent: float = 0.0
        self.message: Context | None = None

    @property
    def text(self) -> str:
        return "".join(self._buffer)

    async def __aenter__(self) -> DraftStream:
        return self

    async def write(self, chunk: str, *, force: bool = False) -> None:
        if not chunk:
            return
        self._buffer.append(chunk)
        await self._flush(force=force)

    async def update(self, full_text: str, *, force: bool = False) -> None:
        self._buffer = [full_text]
        await self._flush(force=force)

    async def _flush(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self.min_interval > 0 and (now - self._last_sent) < self.min_interval:
            return
        fn = self._ctx._resolve_adapter_method("send_message_draft")
        if fn is not None:
            await fn(
                self._ctx.chat_id,
                self.draft_id,
                self.text,
                parse_mode=self.parse_mode,
                can_stop=self.can_stop,
                keep_on_stop=self.keep_on_stop,
            )
            self._last_sent = now

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None or not self.finalize:
            return
        final_text = self.text
        if final_text:
            self.message = await self._ctx.reply(final_text, parse_mode=self.parse_mode)


class RichDraftStream:
    """Async context manager for streaming Bot API 10.1+ Rich Messages."""

    def __init__(
        self,
        ctx: Context,
        *,
        draft_id: int | None = None,
        is_rtl: bool | None = None,
        can_stop: bool = False,
        keep_on_stop: bool = False,
        min_interval: float = 0.25,
        finalize: bool = True,
        mode: str = "html",
    ) -> None:
        self._ctx = ctx
        self.draft_id = int(draft_id) if draft_id is not None else next(_DRAFT_COUNTER)
        self.is_rtl = is_rtl
        self.can_stop = can_stop
        self.keep_on_stop = keep_on_stop
        self.min_interval = max(0.0, float(min_interval))
        self.finalize = finalize
        self.mode = mode
        self._buffer: list[str] = []
        self._blocks: list[dict[str, Any]] | None = None
        self._last_sent: float = 0.0
        self.message: Context | None = None

    @property
    def text(self) -> str:
        return "".join(self._buffer)

    async def __aenter__(self) -> RichDraftStream:
        return self

    async def thinking(self, label: str = "Thinking...") -> None:
        fn = self._ctx._resolve_adapter_method("send_rich_message_draft")
        if fn is not None:
            await fn(
                self._ctx.chat_id,
                self.draft_id,
                blocks=[{"type": "thinking", "text": label}],
                is_rtl=self.is_rtl,
                can_stop=self.can_stop,
                keep_on_stop=self.keep_on_stop,
            )
            self._last_sent = time.monotonic()

    async def write(self, chunk: str, *, force: bool = False) -> None:
        if not chunk:
            return
        self._blocks = None
        self._buffer.append(chunk)
        await self._flush(force=force)

    async def update(
        self,
        *,
        html: str | None = None,
        markdown: str | None = None,
        blocks: Sequence[dict[str, Any]] | None = None,
        force: bool = False,
    ) -> None:
        if blocks is not None:
            self._blocks = list(blocks)
            self._buffer.clear()
        elif html is not None:
            self.mode = "html"
            self._blocks = None
            self._buffer = [html]
        elif markdown is not None:
            self.mode = "markdown"
            self._blocks = None
            self._buffer = [markdown]
        await self._flush(force=force)

    async def _flush(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self.min_interval > 0 and (now - self._last_sent) < self.min_interval:
            return
        fn = self._ctx._resolve_adapter_method("send_rich_message_draft")
        if fn is None:
            return
        kwargs: dict[str, Any] = {
            "is_rtl": self.is_rtl,
            "can_stop": self.can_stop,
            "keep_on_stop": self.keep_on_stop,
        }
        if self._blocks is not None:
            kwargs["blocks"] = self._blocks
        elif self.mode == "markdown":
            kwargs["markdown"] = self.text
        else:
            kwargs["html"] = self.text
        await fn(self._ctx.chat_id, self.draft_id, **kwargs)
        self._last_sent = now

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None or not self.finalize:
            return
        if self._blocks is not None:
            self.message = await self._ctx.reply_rich(blocks=self._blocks, is_rtl=self.is_rtl)
        elif self.text:
            if self.mode == "markdown":
                self.message = await self._ctx.reply_rich(markdown=self.text, is_rtl=self.is_rtl)
            else:
                self.message = await self._ctx.reply_rich(html=self.text, is_rtl=self.is_rtl)


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
        "_dispatcher",
    )

    def __init__(
        self,
        message: MessageEvent,
        adapter: TransportAdapter,
        *,
        task_pool: set[asyncio.Task[Any]] | None = None,
        storage: FSMStorage | None = None,
        fsm_strategy: FSMStrategy = FSMStrategy.USER_IN_CHAT,
        dispatcher: Any = None,
    ) -> None:
        self.message = message
        self.adapter = adapter
        fsm_storage = storage if storage is not None else MemoryStorage()
        sender_id = message.sender.id if message.sender else 0
        topic_id = getattr(message, "message_thread_id", None)
        fsm_key = resolve_fsm_key(fsm_strategy, message.chat.id, sender_id, topic_id=topic_id)
        self.state = FSMContext(fsm_storage, fsm_key)
        self.command: str | None = None
        self.args: list[str] = []
        self.arg_str: str = ""
        self.match: re.Match[str] | None = None
        self._task_pool = task_pool
        self._dispatcher = dispatcher

    async def ask(
        self,
        prompt: str | None = None,
        *,
        timeout: float | None = 60.0,
        filters: Any = None,
        parse_mode: str | None = "html",
        **reply_kwargs: Any,
    ) -> Context:
        """Send an optional prompt and await the next matching reply from this user in this chat."""
        if self._dispatcher is None:
            raise RuntimeError("ctx.ask() requires a Dispatcher-managed Context")
        if prompt is not None:
            await self.reply(prompt, parse_mode=parse_mode, **reply_kwargs)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Context] = loop.create_future()
        user_id = self.sender_id or 0
        self._dispatcher.register_waiter(self.chat_id, user_id, fut, filters)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._dispatcher.cancel_waiter(self.chat_id, user_id, fut)

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

    @property
    def callback_id(self) -> str | None:
        return self.message.callback_id

    @property
    def callback_data(self) -> str | None:
        return self.message.callback_data

    @property
    def inline_query_id(self) -> str | None:
        return self.message.inline_query_id

    @property
    def inline_query(self) -> str | None:
        return self.message.inline_query

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
        reply_markup: dict[str, Any] | None = None,
    ) -> Context:
        kwargs: dict[str, Any] = {"reply_to": self.message.id, "parse_mode": parse_mode}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        sent = await self.adapter.send_message(
            self.chat_id,
            text,
            **kwargs,
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
        reply_markup: dict[str, Any] | None = None,
    ) -> Context:
        kwargs: dict[str, Any] = {"reply_to": None, "parse_mode": parse_mode}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        sent = await self.adapter.send_message(
            self.chat_id,
            text,
            **kwargs,
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
        reply_markup: dict[str, Any] | None = None,
    ) -> Context:
        kwargs: dict[str, Any] = {"parse_mode": parse_mode}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if self.message.inline_message_id:
            kwargs["inline_message_id"] = self.message.inline_message_id
        edited = await self.adapter.edit_message(
            self.chat_id,
            self.message.id,
            text,
            **kwargs,
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

    async def answer_inline(
        self,
        results: list[dict[str, Any]],
        *,
        cache_time: int = 0,
        is_personal: bool = True,
        next_offset: str = "",
    ) -> bool:
        if not self.inline_query_id:
            raise RuntimeError("Context.answer_inline() called on a non-inline-query event.")
        fn = self._resolve_adapter_method("answer_inline_query")
        if fn is None:
            raise RuntimeError("Active adapter does not support answer_inline_query.")
        return bool(
            await fn(
                self.inline_query_id,
                results,
                cache_time=cache_time,
                is_personal=is_personal,
                next_offset=next_offset,
            )
        )

    async def answer(
        self,
        text: str | None = None,
        *,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> None:
        cb_id = self.message.callback_id
        if not cb_id:
            return
        fn = getattr(self.adapter, "answer_callback", None)
        if fn is None:
            raw_adapter = getattr(self.adapter, "raw", None)
            fn = getattr(raw_adapter, "answer_callback", None)
        if fn is not None:
            await fn(cb_id, text, show_alert=show_alert, url=url, cache_time=cache_time)

    def _resolve_adapter_method(self, name: str) -> Any:
        fn = getattr(self.adapter, name, None)
        if fn is None:
            raw_adapter = getattr(self.adapter, "raw", None)
            fn = getattr(raw_adapter, name, None)
        return fn

    async def reply_ephemeral(
        self,
        text: str,
        *,
        receiver_user_id: int | None = None,
        replace: bool = False,
        parse_mode: str | None = "html",
        reply_markup: dict[str, Any] | None = None,
    ) -> Context:
        """Send an ephemeral reply visible only to the triggering user (Bot API 10.2+)."""
        fn = self._resolve_adapter_method("send_ephemeral_message")
        if fn is None:
            raise AttributeError("Current adapter does not support send_ephemeral_message.")
        uid = receiver_user_id if receiver_user_id is not None else self.sender_id
        sent = await fn(
            self.chat_id,
            text,
            receiver_user_id=uid,
            callback_query_id=self.message.callback_id,
            replace_callback_query_message=replace,
            reply_to=self.message.id if not self.message.callback_id else None,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return Context(
            sent,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    def stream(
        self,
        *,
        draft_id: int | None = None,
        parse_mode: str | None = "html",
        can_stop: bool = False,
        keep_on_stop: bool = False,
        min_interval: float = 0.25,
        finalize: bool = True,
    ) -> DraftStream:
        """Stream partial replies live using Bot API sendMessageDraft."""
        return DraftStream(
            self,
            draft_id=draft_id,
            parse_mode=parse_mode,
            can_stop=can_stop,
            keep_on_stop=keep_on_stop,
            min_interval=min_interval,
            finalize=finalize,
        )

    async def set_member_tag(
        self,
        tag: str | None = None,
        *,
        user_id: int | str | None = None,
    ) -> bool:
        """Set or clear a member's text tag in the current group (Bot API 9.5+)."""
        fn = self._resolve_adapter_method("set_chat_member_tag")
        if fn is None:
            raise AttributeError("Current adapter does not support set_chat_member_tag.")
        target_uid = user_id if user_id is not None else self.sender_id
        if target_uid is None:
            raise ValueError("Cannot determine user_id for set_member_tag.")
        return bool(await fn(self.chat_id, target_uid, tag))

    async def reply_rich(
        self,
        rich_msg: dict[str, Any] | None = None,
        *,
        html: str | None = None,
        markdown: str | None = None,
        blocks: Sequence[dict[str, Any]] | None = None,
        media: Sequence[dict[str, Any]] | None = None,
        is_rtl: bool | None = None,
        skip_entity_detection: bool | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Context:
        """Reply with a Bot API 10.1+ Rich Message."""
        fn = self._resolve_adapter_method("send_rich_message")
        if fn is None:
            raise AttributeError("Current adapter does not support send_rich_message.")
        sent = await fn(
            self.chat_id,
            rich_msg,
            html=html,
            markdown=markdown,
            blocks=blocks,
            media=media,
            is_rtl=is_rtl,
            skip_entity_detection=skip_entity_detection,
            reply_to=self.message.id,
            reply_markup=reply_markup,
        )
        return Context(
            sent,
            self.adapter,
            task_pool=self._task_pool,
            storage=self.state.storage,
        )

    def stream_rich(
        self,
        *,
        draft_id: int | None = None,
        is_rtl: bool | None = None,
        can_stop: bool = False,
        keep_on_stop: bool = False,
        min_interval: float = 0.25,
        finalize: bool = True,
        mode: str = "html",
    ) -> RichDraftStream:
        """Stream partial Rich Messages live using Bot API sendRichMessageDraft."""
        return RichDraftStream(
            self,
            draft_id=draft_id,
            is_rtl=is_rtl,
            can_stop=can_stop,
            keep_on_stop=keep_on_stop,
            min_interval=min_interval,
            finalize=finalize,
            mode=mode,
        )
