from __future__ import annotations

import operator
from collections.abc import Callable, Container
from typing import Any

from shirdal.engine.context import Context
from shirdal.engine.filters import Filter

_MISSING = object()


class MagicFilter(Filter):
    """Lightweight, dependency-free expression filter (e.g., F.text.startswith('http'))."""

    def __init__(self, resolver: Callable[[Context], Any] | None = None) -> None:
        self._resolver = resolver if resolver is not None else (lambda ctx: ctx)

    def resolve(self, ctx: Context) -> Any:
        try:
            return self._resolver(ctx)
        except (AttributeError, KeyError, IndexError, TypeError):
            return _MISSING

    async def check(self, ctx: Context) -> bool:
        val = self.resolve(ctx)
        if val is _MISSING:
            return False
        return bool(val)

    def __getattr__(self, name: str) -> MagicFilter:
        if name.startswith("_"):
            raise AttributeError(name)

        def _next(ctx: Context) -> Any:
            val = self.resolve(ctx)
            if val is _MISSING or val is None:
                return _MISSING
            if isinstance(val, dict) and name in val:
                return val[name]
            return getattr(val, name, _MISSING)

        return MagicFilter(_next)

    def __getitem__(self, key: Any) -> MagicFilter:
        def _next(ctx: Context) -> Any:
            val = self.resolve(ctx)
            if val is _MISSING or val is None:
                return _MISSING
            return val[key]

        return MagicFilter(_next)

    def _cmp(self, op: Callable[[Any, Any], bool], other: Any) -> MagicFilter:
        def _next(ctx: Context) -> bool:
            val = self.resolve(ctx)
            if val is _MISSING:
                return False
            return bool(op(val, other))

        return MagicFilter(_next)

    def __eq__(self, other: object) -> MagicFilter:  # type: ignore[override]
        return self._cmp(operator.eq, other)

    def __ne__(self, other: object) -> MagicFilter:  # type: ignore[override]
        return self._cmp(operator.ne, other)

    def __lt__(self, other: Any) -> MagicFilter:
        return self._cmp(operator.lt, other)

    def __le__(self, other: Any) -> MagicFilter:
        return self._cmp(operator.le, other)

    def __gt__(self, other: Any) -> MagicFilter:
        return self._cmp(operator.gt, other)

    def __ge__(self, other: Any) -> MagicFilter:
        return self._cmp(operator.ge, other)

    def in_(self, container: Container[Any]) -> MagicFilter:
        def _next(ctx: Context) -> bool:
            val = self.resolve(ctx)
            return val is not _MISSING and val in container

        return MagicFilter(_next)

    def startswith(self, prefix: str | tuple[str, ...]) -> MagicFilter:
        def _next(ctx: Context) -> bool:
            val = self.resolve(ctx)
            return isinstance(val, str) and val.startswith(prefix)

        return MagicFilter(_next)

    def endswith(self, suffix: str | tuple[str, ...]) -> MagicFilter:
        def _next(ctx: Context) -> bool:
            val = self.resolve(ctx)
            return isinstance(val, str) and val.endswith(suffix)

        return MagicFilter(_next)

    def contains(self, sub: Any) -> MagicFilter:
        def _next(ctx: Context) -> bool:
            val = self.resolve(ctx)
            if val is _MISSING or val is None:
                return False
            return sub in val

        return MagicFilter(_next)

    def lower(self) -> MagicFilter:
        def _next(ctx: Context) -> Any:
            val = self.resolve(ctx)
            return val.lower() if isinstance(val, str) else _MISSING

        return MagicFilter(_next)

    def strip(self) -> MagicFilter:
        def _next(ctx: Context) -> Any:
            val = self.resolve(ctx)
            return val.strip() if isinstance(val, str) else _MISSING

        return MagicFilter(_next)


F = MagicFilter()
