from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shirdal.engine.context import Context

NextHandler = Callable[["Context"], Awaitable[Any]]


@runtime_checkable
class Middleware(Protocol):
    """Onion-style middleware wrapping Context handler execution."""

    async def __call__(self, ctx: Context, call_next: NextHandler) -> Any: ...
