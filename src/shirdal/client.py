from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, overload

from shirdal.core.adapter import TransportAdapter
from shirdal.core.events import EventType, UpdateEvent
from shirdal.engine.dispatcher import ContextHandler, Dispatcher, ErrorHandler
from shirdal.engine.filters import Filter, command, incoming
from shirdal.engine.fsm import FSMStorage, FSMStrategy
from shirdal.engine.router import Router
from shirdal.engine.scheduler import JobFunc, Scheduler
from shirdal.guard.antiflood import AntiFloodAdapter, AntiFloodConfig
from shirdal.guard.middleware import Middleware
from shirdal.plugins.loader import PluginManager

_LOG = logging.getLogger("shirdal")


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
        fsm_strategy: FSMStrategy = FSMStrategy.USER_IN_CHAT,
        startup_banner: bool = True,
    ) -> None:
        self.raw_adapter = adapter
        self.adapter: TransportAdapter = (
            AntiFloodAdapter(adapter, config=flood_config) if anti_flood else adapter
        )
        self._use_uvloop = use_uvloop
        self._startup_banner = startup_banner
        self._tasks: set[asyncio.Task[Any]] = set()
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._startup_info_task: asyncio.Task[Any] | None = None
        self.dispatcher = Dispatcher(task_pool=self._tasks, storage=storage, fsm_strategy=fsm_strategy)
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

    def include_router(self, router: Router) -> Router:
        router.attach_to(self.dispatcher, plugin_name=self._active_plugin_scope)
        return router

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

    def on_command(
        self,
        names: str | Sequence[str],
        *,
        prefix: str | Sequence[str] = "/",
        case_sensitive: bool = False,
        only_incoming: bool = True,
    ) -> Callable[[ContextHandler], ContextHandler]:
        """Register a command handler (defaults to incoming messages with '/' prefix)."""
        cmd_filter: Filter = command(names, prefix=prefix, case_sensitive=case_sensitive)
        if only_incoming:
            cmd_filter = incoming & cmd_filter
        return self.on(cmd_filter, event_type=EventType.NEW_MESSAGE)

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

    @overload
    def on_message(self, target: ContextHandler) -> ContextHandler: ...

    @overload
    def on_message(
        self, target: Filter | None = None
    ) -> Callable[[ContextHandler], ContextHandler]: ...

    def on_message(
        self, target: ContextHandler | Filter | None = None
    ) -> ContextHandler | Callable[[ContextHandler], ContextHandler]:
        """Register a message handler, supporting both @bot.on_message and @bot.on_message(filter)."""
        if callable(target) and not isinstance(target, Filter):
            return self.dispatcher.register(
                None, target, plugin_name=self._active_plugin_scope
            )
        return self.on(target, event_type=EventType.NEW_MESSAGE)

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

    @staticmethod
    def _detect_runtime_extensions() -> tuple[str, str, str]:
        try:
            loop_name = type(asyncio.get_running_loop()).__module__.split(".")[0]
            if "uvloop" in loop_name:
                loop_label = "uvloop"
            else:
                loop_label = "asyncio"
        except Exception:
            loop_label = "asyncio"

        try:
            import msgspec  # type: ignore[import-not-found]  # noqa: F401
            json_label = "msgspec"
        except ImportError:
            json_label = "json"

        try:
            import sys

            crypto_mod = sys.modules.get("shirdal.mtproto.crypto")
            if crypto_mod is not None:
                crypto_label = crypto_mod.crypto_backend()
            else:
                crypto_label = "not loaded"
        except Exception:
            crypto_label = "unavailable"

        return loop_label, json_label, crypto_label

    async def _probe_startup_ping(self, connect_ms: float | None = None) -> tuple[str | None, float | None]:
        """Measure initial API latency (ms) and identity if supported by the adapter."""
        adapter = self.raw_adapter
        if type(adapter).__name__ == "MockAdapter":
            return None, None
        cached_username = getattr(adapter, "bot_username", None)
        if cached_username:
            identity = f"@{cached_username}" if not str(cached_username).startswith("@") else cached_username
            return identity, connect_ms
        t0 = time.perf_counter()
        try:
            me = await asyncio.wait_for(adapter.invoke("getMe"), timeout=5.0)
            ping_ms = (time.perf_counter() - t0) * 1000.0
            username: str | None = None
            if isinstance(me, dict):
                username = me.get("username") or me.get("first_name")
            else:
                username = getattr(me, "username", None) or getattr(me, "first_name", None)
            identity = f"@{username}" if username and not str(username).startswith("@") else username
            return identity, ping_ms
        except Exception:
            return None, connect_ms

    def _emit_line(self, line: str) -> None:
        if _LOG.isEnabledFor(logging.INFO):
            _LOG.info(line)
        elif self._startup_banner:
            print(line, file=sys.stdout, flush=True)

    @staticmethod
    def _banner_palette() -> tuple[str, str, str, str, str, str]:
        import os
        use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        if use_color and sys.platform == "win32":
            os.system("")
        if not use_color:
            return "", "", "", "", "", ""
        return "\033[1;33m", "\033[1;36m", "\033[1;32m", "\033[1m", "\033[2m", "\033[0m"

    @staticmethod
    def _pkg_version() -> str:
        try:
            from importlib.metadata import version
            return version("shirdal")
        except Exception:
            try:
                from shirdal import __version__
                return __version__
            except Exception:
                return "unknown"

    async def _log_startup_info(
        self, connect_ms: float | None = None, *, _progressive: bool = False
    ) -> str:
        """Log version, identity, ping, and active acceleration extensions."""
        shirdal_version = self._pkg_version()
        loop_label, json_label, crypto_label = self._detect_runtime_extensions()
        adapter_name = type(self.raw_adapter).__name__
        gold, teal, green, bold, dim, reset = self._banner_palette()

        identity, ping_ms = await self._probe_startup_ping(connect_ms=connect_ms)
        lines = [
            f"{gold}shirdal {shirdal_version}{reset}",
            f"{dim}adapter:{reset} {teal}{adapter_name}{reset}",
            f"{dim}loop:{reset}    {bold}{loop_label}{reset}",
            f"{dim}json:{reset}    {bold}{json_label}{reset}",
            f"{dim}crypto:{reset}  {green}{crypto_label}{reset}",
        ]
        if identity:
            lines.append(f"{dim}bot:{reset}     {green}{identity}{reset}")

        ping_line = f"{dim}ping:{reset}    {bold}{ping_ms:.1f}ms{reset}" if ping_ms is not None else None

        for ln in lines:
            self._emit_line(ln)

        if ping_line is not None:
            if _progressive and self._startup_banner and not _LOG.isEnabledFor(logging.INFO) and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
                print(f"\n{ping_line}", end="", file=sys.stdout, flush=True)
            else:
                self._emit_line(ping_line)
            lines.append(ping_line)

        return "\n".join(lines)

    async def _heartbeat_loop(self, interval: float = 60.0) -> None:
        _, _, _, bold, dim, reset = self._banner_palette()
        is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and self._startup_banner and not _LOG.isEnabledFor(logging.INFO)
        try:
            while self._running:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                try:
                    _, ping_ms = await self._probe_startup_ping()
                    if ping_ms is not None:
                        line = f"{dim}ping:{reset}    {bold}{ping_ms:.1f}ms{reset}"
                        if is_tty:
                            print(f"\r\033[2K{line}", end="", file=sys.stdout, flush=True)
                        else:
                            self._emit_line(line)
                except Exception:
                    pass
        except asyncio.CancelledError:
            if is_tty:
                print(file=sys.stdout, flush=True)

    async def start(self) -> None:
        gold, _, _, _, _, reset = self._banner_palette()
        self._emit_line(f"{gold}Bot is running...{reset}")

        t0 = time.perf_counter()
        await self.adapter.connect()
        connect_ms = (time.perf_counter() - t0) * 1000.0
        self._running = True
        self._startup_info_task = asyncio.create_task(
            self._log_startup_info(connect_ms=connect_ms, _progressive=True)
        )
        if self._startup_banner:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(60.0))
        if self.plugins is not None:
            await self.plugins.load_all()
            if self._hot_reload:
                self._watcher_task = asyncio.create_task(
                    self.plugins.watch_loop(self._reload_interval)
                )
        self.scheduler.start()

    async def stop(self) -> None:
        self._running = False
        si = getattr(self, "_startup_info_task", None)
        if si is not None:
            si.cancel()
            await asyncio.gather(si, return_exceptions=True)
            self._startup_info_task = None
        hb = getattr(self, "_heartbeat_task", None)
        if hb is not None:
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
            self._heartbeat_task = None
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
