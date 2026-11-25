from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shirdal.client import SelfBot


@dataclass(slots=True)
class PluginLoadResult:
    loaded: list[str] = field(default_factory=list)
    reloaded: list[str] = field(default_factory=list)
    unloaded: list[str] = field(default_factory=list)
    errors: dict[str, Exception] = field(default_factory=dict)


@dataclass(slots=True)
class _LoadedPlugin:
    name: str
    path: Path
    mtime_ns: int
    module: ModuleType


class PluginManager:
    """Loads, unloads, and hot-reloads plugin modules without disconnecting."""

    def __init__(self, bot: SelfBot, plugins_dir: str | Path) -> None:
        self.bot = bot
        self.plugins_dir = Path(plugins_dir)
        self._plugins: dict[str, _LoadedPlugin] = {}

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    def _discover_files(self) -> dict[str, Path]:
        if not self.plugins_dir.exists():
            return {}
        discovered: dict[str, Path] = {}
        for path in sorted(self.plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            discovered[path.stem] = path
        return discovered

    async def _call_hook(self, fn: Any) -> None:
        res = fn(self.bot)
        if inspect.isawaitable(res):
            await res

    async def load_plugin(self, path: Path) -> str:
        name = path.stem
        if name in self._plugins:
            await self.unload_plugin(name)

        mod_name = f"shirdal_plugin_{name}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin spec from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module

        prev_scope = self.bot._active_plugin_scope
        self.bot._active_plugin_scope = name
        try:
            spec.loader.exec_module(module)
            setup_fn = getattr(module, "setup", None)
            if callable(setup_fn):
                await self._call_hook(setup_fn)
        except Exception:
            self.bot.dispatcher.unregister_plugin(name)
            self.bot.scheduler.unregister_plugin(name)
            sys.modules.pop(mod_name, None)
            raise
        finally:
            self.bot._active_plugin_scope = prev_scope

        mtime_ns = path.stat().st_mtime_ns
        self._plugins[name] = _LoadedPlugin(
            name=name,
            path=path,
            mtime_ns=mtime_ns,
            module=module,
        )
        return name

    async def unload_plugin(self, name: str) -> bool:
        entry = self._plugins.pop(name, None)
        if entry is None:
            return False

        teardown_fn = getattr(entry.module, "teardown", None)
        if callable(teardown_fn):
            await self._call_hook(teardown_fn)

        self.bot.dispatcher.unregister_plugin(name)
        self.bot.scheduler.unregister_plugin(name)
        sys.modules.pop(f"shirdal_plugin_{name}", None)
        return True

    async def load_all(self) -> PluginLoadResult:
        return await self.scan_changes()

    async def scan_changes(self) -> PluginLoadResult:
        result = PluginLoadResult()
        current_files = self._discover_files()

        for existing_name in list(self._plugins.keys()):
            if existing_name not in current_files:
                await self.unload_plugin(existing_name)
                result.unloaded.append(existing_name)

        for name, path in current_files.items():
            try:
                mtime_ns = path.stat().st_mtime_ns
            except FileNotFoundError:
                continue

            existing = self._plugins.get(name)
            if existing is None:
                try:
                    await self.load_plugin(path)
                    result.loaded.append(name)
                except Exception as exc:
                    result.errors[name] = exc
            elif existing.mtime_ns != mtime_ns:
                try:
                    await self.load_plugin(path)
                    result.reloaded.append(name)
                except Exception as exc:
                    result.errors[name] = exc

        return result

    async def watch_loop(self, interval: float = 1.0) -> None:
        while self.bot._running:
            await asyncio.sleep(interval)
            if not self.bot._running:
                break
            await self.scan_changes()
