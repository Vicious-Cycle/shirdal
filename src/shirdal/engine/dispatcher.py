from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import EventType, UpdateEvent
from shirdal.engine.context import Context
from shirdal.engine.filters import Filter
from shirdal.engine.fsm import FSMStorage, FSMStrategy, MemoryStorage
from shirdal.guard.middleware import Middleware, NextHandler

logger = logging.getLogger("shirdal.dispatcher")

ContextHandler = Callable[[Context], Awaitable[Any]]
ErrorHandler = Callable[[Context, Exception], Awaitable[Any]]
WaiterKey = tuple[int, int]  # (chat_id, user_id)


@dataclass(slots=True)
class _Route:
    filter_obj: Filter | None
    handler: ContextHandler
    event_type: EventType = EventType.NEW_MESSAGE
    plugin_name: str | None = None
    chain: NextHandler | None = field(default=None, repr=False)


class Dispatcher:
    """Routes UpdateEvents through waiters, middlewares, filters, and global error handlers."""

    def __init__(
        self,
        task_pool: set[asyncio.Task[Any]] | None = None,
        storage: FSMStorage | None = None,
        fsm_strategy: FSMStrategy = FSMStrategy.USER_IN_CHAT,
    ) -> None:
        self._routes: list[_Route] = []
        self._middlewares: list[Middleware] = []
        self._error_handlers: list[ErrorHandler] = []
        self._task_pool = task_pool if task_pool is not None else set()
        self.storage: FSMStorage = storage if storage is not None else MemoryStorage()
        self.fsm_strategy = fsm_strategy
        self._waiters: dict[WaiterKey, list[tuple[Filter | None, asyncio.Future[Context]]]] = {}

    def register_waiter(
        self,
        chat_id: int,
        user_id: int,
        future: asyncio.Future[Context],
        filter_obj: Filter | None = None,
    ) -> None:
        self._waiters.setdefault((chat_id, user_id), []).append((filter_obj, future))

    def cancel_waiter(
        self,
        chat_id: int,
        user_id: int,
        future: asyncio.Future[Context],
    ) -> None:
        key = (chat_id, user_id)
        entries = self._waiters.get(key)
        if not entries:
            return
        remaining = [(f, fut) for f, fut in entries if fut is not future]
        if remaining:
            self._waiters[key] = remaining
        else:
            self._waiters.pop(key, None)

    def add_middleware(self, middleware: Middleware) -> Middleware:
        self._middlewares.append(middleware)
        for route in self._routes:
            route.chain = self._build_chain(route.handler)
        return middleware

    def register_error_handler(self, handler: ErrorHandler) -> ErrorHandler:
        self._error_handlers.append(handler)
        return handler

    def register(
        self,
        filter_obj: Filter | None,
        handler: ContextHandler,
        *,
        event_type: EventType = EventType.NEW_MESSAGE,
        plugin_name: str | None = None,
    ) -> ContextHandler:
        self._routes.append(
            _Route(
                filter_obj=filter_obj,
                handler=handler,
                event_type=event_type,
                plugin_name=plugin_name,
                chain=self._build_chain(handler),
            )
        )
        return handler

    def unregister_plugin(self, plugin_name: str) -> int:
        before = len(self._routes)
        self._routes = [r for r in self._routes if r.plugin_name != plugin_name]
        return before - len(self._routes)

    def _build_chain(self, handler: ContextHandler) -> NextHandler:
        call_next: NextHandler = handler
        for mw in reversed(self._middlewares):
            prev = call_next

            async def _wrapped(c: Context, _mw: Middleware = mw, _next: NextHandler = prev) -> Any:
                return await _mw(c, _next)

            call_next = _wrapped
        return call_next

    async def _run_safe(self, chain: NextHandler, ctx: Context) -> None:
        try:
            await chain(ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Unhandled exception in handler for message %s", ctx.id)
            for err_handler in list(self._error_handlers):
                try:
                    await err_handler(ctx, exc)
                except Exception:
                    logger.exception("Error inside on_error handler")

    async def _try_resolve_waiter(
        self, update: UpdateEvent, adapter: TransportAdapter
    ) -> bool:
        if update.type != EventType.NEW_MESSAGE or update.message is None:
            return False
        msg = update.message
        sender_id = msg.sender.id if msg.sender else 0
        key = (msg.chat.id, sender_id)
        entries = self._waiters.get(key)
        if not entries:
            return False

        ctx = Context(
            msg,
            adapter,
            task_pool=self._task_pool,
            storage=self.storage,
            fsm_strategy=self.fsm_strategy,
            dispatcher=self,
        )
        for idx, (flt, fut) in enumerate(list(entries)):
            if fut.done():
                continue
            if flt is not None and not await flt.check(ctx):
                ctx.command = None
                ctx.args = []
                ctx.arg_str = ""
                ctx.match = None
                continue
            entries.pop(idx)
            if not entries:
                self._waiters.pop(key, None)
            fut.set_result(ctx)
            return True
        return False

    async def dispatch(self, update: UpdateEvent, adapter: TransportAdapter) -> None:
        if update.message is None:
            return

        if await self._try_resolve_waiter(update, adapter):
            return

        ctx: Context | None = None
        for route in list(self._routes):
            if route.event_type != update.type:
                continue
            if ctx is None:
                ctx = Context(
                    update.message,
                    adapter,
                    task_pool=self._task_pool,
                    storage=self.storage,
                    fsm_strategy=self.fsm_strategy,
                    dispatcher=self,
                )
            else:
                ctx.command = None
                ctx.args = []
                ctx.arg_str = ""
                ctx.match = None

            if route.filter_obj is not None and not await route.filter_obj.check(ctx):
                continue

            chain = route.chain if route.chain is not None else self._build_chain(route.handler)
            dispatched_ctx = ctx
            ctx = None
            task = asyncio.create_task(self._run_safe(chain, dispatched_ctx))
            self._task_pool.add(task)
            task.add_done_callback(self._task_pool.discard)
