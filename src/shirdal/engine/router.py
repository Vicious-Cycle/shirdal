from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shirdal.core.events import EventType
from shirdal.engine.context import Context
from shirdal.engine.dispatcher import ContextHandler, Dispatcher
from shirdal.engine.filters import Filter
from shirdal.guard.middleware import Middleware, NextHandler


@dataclass(slots=True)
class _RouterEntry:
    filter_obj: Filter | None
    handler: ContextHandler
    event_type: EventType


def _wrap_handler(handler: ContextHandler, middlewares: list[Middleware]) -> ContextHandler:
    if not middlewares:
        return handler
    call_next: NextHandler = handler
    for mw in reversed(middlewares):
        prev = call_next

        async def _wrapped(ctx: Context, _mw: Middleware = mw, _next: NextHandler = prev) -> Any:
            return await _mw(ctx, _next)

        call_next = _wrapped
    return call_next


class Router:
    """Modular, nestable handler router (similar to aiogram's Router)."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or "router"
        self._entries: list[_RouterEntry] = []
        self._middlewares: list[Middleware] = []
        self._children: list[Router] = []

    def use(self, middleware: Middleware) -> Middleware:
        self._middlewares.append(middleware)
        return middleware

    def include_router(self, router: Router) -> Router:
        if router is self:
            raise ValueError("Cannot include a router into itself")
        self._children.append(router)
        return router

    def on(
        self,
        filter_obj: Filter | None = None,
        *,
        event_type: EventType = EventType.NEW_MESSAGE,
    ) -> Callable[[ContextHandler], ContextHandler]:
        def decorator(func: ContextHandler) -> ContextHandler:
            self._entries.append(
                _RouterEntry(filter_obj=filter_obj, handler=func, event_type=event_type)
            )
            return func

        return decorator

    def on_callback(
        self, filter_obj: Filter | None = None
    ) -> Callable[[ContextHandler], ContextHandler]:
        return self.on(filter_obj, event_type=EventType.CALLBACK_QUERY)

    def on_edit(
        self, filter_obj: Filter | None = None
    ) -> Callable[[ContextHandler], ContextHandler]:
        return self.on(filter_obj, event_type=EventType.EDIT_MESSAGE)

    def on_message(self, func: ContextHandler) -> ContextHandler:
        self._entries.append(
            _RouterEntry(filter_obj=None, handler=func, event_type=EventType.NEW_MESSAGE)
        )
        return func

    def attach_to(
        self,
        dispatcher: Dispatcher,
        *,
        inherited_middlewares: list[Middleware] | None = None,
        plugin_name: str | None = None,
    ) -> None:
        combined_mw = [*(inherited_middlewares or []), *self._middlewares]
        for entry in self._entries:
            wrapped = _wrap_handler(entry.handler, combined_mw)
            dispatcher.register(
                entry.filter_obj,
                wrapped,
                event_type=entry.event_type,
                plugin_name=plugin_name,
            )
        for child in self._children:
            child.attach_to(
                dispatcher,
                inherited_middlewares=combined_mw,
                plugin_name=plugin_name,
            )
