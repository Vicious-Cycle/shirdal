from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from shirdal.client import SelfBot
from shirdal.core.adapter import TransportAdapter
from shirdal.engine.dispatcher import ContextHandler
from shirdal.engine.filters import Filter
from shirdal.guard.antiflood import AntiFloodAdapter
from shirdal.guard.middleware import Middleware


class MultiBot:
    """Manage and run multiple SelfBot accounts concurrently under one control plane."""

    def __init__(self, *, use_uvloop: bool = True) -> None:
        self._use_uvloop = use_uvloop
        self._bots: dict[str, SelfBot] = {}
        self._serve_tasks: dict[str, asyncio.Task[Any]] = {}
        self._shared_routes: list[tuple[Filter | None, ContextHandler]] = []
        self._shared_middlewares: list[Middleware] = []

    @property
    def accounts(self) -> list[str]:
        return list(self._bots.keys())

    def get(self, name: str) -> SelfBot:
        return self._bots[name]

    def add(self, name: str, bot: SelfBot) -> SelfBot:
        if name in self._bots:
            raise ValueError(f"Account '{name}' is already registered.")
        for mw in self._shared_middlewares:
            bot.use(mw)
        for filter_obj, handler in self._shared_routes:
            bot.dispatcher.register(filter_obj, handler, plugin_name="__multibot__")
        self._bots[name] = bot
        return bot

    def add_adapter(
        self, name: str, adapter: TransportAdapter, **bot_kwargs: Any
    ) -> SelfBot:
        bot = SelfBot(adapter, use_uvloop=self._use_uvloop, **bot_kwargs)
        return self.add(name, bot)

    def use(self, middleware: Middleware) -> Middleware:
        """Register a shared middleware across all current and future accounts."""
        self._shared_middlewares.append(middleware)
        for bot in self._bots.values():
            bot.use(middleware)
        return middleware

    def on(
        self, filter_obj: Filter | None = None
    ) -> Callable[[ContextHandler], ContextHandler]:
        """Register a shared handler across all current and future accounts."""

        def decorator(func: ContextHandler) -> ContextHandler:
            self._shared_routes.append((filter_obj, func))
            for bot in self._bots.values():
                bot.dispatcher.register(filter_obj, func, plugin_name="__multibot__")
            return func

        return decorator

    def status(self) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        for name, bot in self._bots.items():
            flood_stats = (
                bot.adapter.stats if isinstance(bot.adapter, AntiFloodAdapter) else None
            )
            report[name] = {
                "connected": bot.adapter.is_connected,
                "running": bot._running,
                "plugins": bot.plugins.loaded_plugins if bot.plugins else [],
                "flood_stats": flood_stats,
            }
        return report

    async def start_account(self, name: str) -> None:
        bot = self._bots[name]
        existing = self._serve_tasks.get(name)
        if existing is not None and not existing.done():
            return
        self._serve_tasks[name] = asyncio.create_task(bot.serve())

    async def stop_account(self, name: str) -> None:
        bot = self._bots[name]
        await bot.stop()
        task = self._serve_tasks.pop(name, None)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def serve_all(self) -> None:
        for name in list(self._bots.keys()):
            await self.start_account(name)
        try:
            if self._serve_tasks:
                await asyncio.gather(*list(self._serve_tasks.values()))
        finally:
            await self.stop_all()

    async def stop_all(self) -> None:
        for name in list(self._bots.keys()):
            await self.stop_account(name)

    def run(self) -> None:
        if self._use_uvloop:
            try:
                import uvloop  # type: ignore[import-not-found]
                uvloop.install()
            except ImportError:
                pass
        asyncio.run(self.serve_all())
