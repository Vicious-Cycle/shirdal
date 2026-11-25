from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import EventType, UpdateEvent
from shirdal.engine.dispatcher import ContextHandler, Dispatcher, ErrorHandler
from shirdal.engine.filters import Filter
from shirdal.engine.fsm import FSMStorage
from shirdal.engine.scheduler import JobFunc, Scheduler
from shirdal.guard.antiflood import AntiFloodAdapter, AntiFloodConfig
from shirdal.guard.middleware import Middleware
from shirdal.plugins.loader import PluginManager


class Shirdal:
    """Main entry point for a shirdal Telegram bot or MTProto client."""

    def __init__(
        self,
        adapter: TransportAdapter,
        *,
        use_uvloop: bool = True,
        anti_flood: bool = True,
        flood_config: AntiFloodConfig | None = None,
        plugins_dir: str | Path | None = None,
        hot_reload: bool = False,
        reload_interval: float = 1.0,
        storage: FSMStorage | None = None,
    ) -> None:
        self.raw_adapter = adapter
        self.adapter: TransportAdapter = (
            AntiFloodAdapter(adapter, config=flood_config) if anti_flood else adapter
        )
        self._use_uvloop = use_uvloop
        self._tasks: set[asyncio.Task[Any]] = set()
        self.dispatcher = Dispatcher(task_pool=self._tasks, storage=storage)
        self.scheduler = Scheduler(self)
        self._running = False
        self._active_plugin_scope: str | None = None

        self.plugins: PluginManager | None = (
            PluginManager(self, plugins_dir) if plugins_dir is not None else None
        )
        self._hot_reload = hot_reload
        self._reload_interval = reload_interval
        self._watcher_task: asyncio.Task[Any] | None = None

    def use(self, middleware: Middleware) -> Middleware:
        return self.dispatcher.add_middleware(middleware)

    def on(
        self,
        filter_obj: Filter | None = None,
        *,
        event_type: EventType = EventType.NEW_MESSAGE,
    ) -> Callable[[ContextHandler], ContextHandler]:
        def decorator(func: ContextHandler) -> ContextHandler:
            return self.dispatcher.register(
                filter_obj,
                func,
                event_type=event_type,
                plugin_name=self._active_plugin_scope,
            )

        return decorator

    def on_callback(
        self,
        filter_obj: Filter | None = None,
    ) -> Callable[[ContextHandler], ContextHandler]:
        return self.on(filter_obj, event_type=EventType.CALLBACK_QUERY)

    def on_edit(
        self, filter_obj: Filter | None = None
    ) -> Callable[[ContextHandler], ContextHandler]:
        """Register a handler for edited messages."""
        return self.on(filter_obj, event_type=EventType.EDIT_MESSAGE)

    def on_message(self, func: ContextHandler) -> ContextHandler:
        return self.dispatcher.register(
            None, func, plugin_name=self._active_plugin_scope
        )

    def on_error(self, func: ErrorHandler) -> ErrorHandler:
        """Register a global error handler receiving (ctx, exception)."""
        return self.dispatcher.register_error_handler(func)

    def every(
        self,
        *,
        seconds: float = 0.0,
        minutes: float = 0.0,
        hours: float = 0.0,
        run_immediately: bool = False,
    ) -> Callable[[JobFunc], JobFunc]:
        total_seconds = seconds + (minutes * 60.0) + (hours * 3600.0)

        def decorator(func: JobFunc) -> JobFunc:
            self.scheduler.add_periodic(
                total_seconds,
                func,
                run_immediately=run_immediately,
                plugin_name=self._active_plugin_scope,
            )
            return func

        return decorator

    def after(self, delay: float, func: JobFunc) -> asyncio.Task[Any]:
        return self.scheduler.schedule_once(delay, func)

    async def start(self) -> None:
        await self.adapter.connect()
        self._running = True
        if self.plugins is not None:
            await self.plugins.load_all()
            if self._hot_reload:
                self._watcher_task = asyncio.create_task(
                    self.plugins.watch_loop(self._reload_interval)
                )
        self.scheduler.start()

    async def stop(self) -> None:
        self._running = False
        await self.scheduler.stop()
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            await asyncio.gather(self._watcher_task, return_exceptions=True)
            self._watcher_task = None
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            self._tasks.clear()
        await self.adapter.disconnect()
        close_fn = getattr(self.dispatcher.storage, "close", None)
        if callable(close_fn):
            close_fn()

    async def _dispatch_update(self, update: UpdateEvent) -> None:
        await self.dispatcher.dispatch(update, self.adapter)

    async def serve(self) -> None:
        await self.start()
        try:
            async for update in self.adapter.listen():
                if not self._running:
                    break
                await self._dispatch_update(update)
        finally:
            await self.stop()

    def run(self) -> None:
        if self._use_uvloop:
            try:
                import uvloop  # type: ignore[import-not-found]
                uvloop.install()
            except ImportError:
                pass
        asyncio.run(self.serve())


SelfBot = Shirdal
