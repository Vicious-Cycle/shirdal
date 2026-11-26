from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

from shirdal.engine.context import Context
from shirdal.engine.fsm import ANY_STATE, State


class Filter(ABC):
    """Base composable filter supporting &, |, and ~ operators."""

    @abstractmethod
    async def check(self, ctx: Context) -> bool: ...

    def __and__(self, other: Filter) -> Filter:
        return _AndFilter(self, other)

    def __or__(self, other: Filter) -> Filter:
        return _OrFilter(self, other)

    def __invert__(self) -> Filter:
        return _NotFilter(self)


class _AndFilter(Filter):
    def __init__(self, left: Filter, right: Filter) -> None:
        self.left = left
        self.right = right

    async def check(self, ctx: Context) -> bool:
        return await self.left.check(ctx) and await self.right.check(ctx)


class _OrFilter(Filter):
    def __init__(self, left: Filter, right: Filter) -> None:
        self.left = left
        self.right = right

    async def check(self, ctx: Context) -> bool:
        return await self.left.check(ctx) or await self.right.check(ctx)


class _NotFilter(Filter):
    def __init__(self, inner: Filter) -> None:
        self.inner = inner

    async def check(self, ctx: Context) -> bool:
        return not await self.inner.check(ctx)


class _PredicateFilter(Filter):
    def __init__(self, fn) -> None:
        self._fn = fn

    async def check(self, ctx: Context) -> bool:
        return bool(self._fn(ctx))


class CommandFilter(Filter):
    """Matches self-bot commands and populates ctx.command, ctx.args, ctx.arg_str."""

    def __init__(
        self,
        names: str | Sequence[str],
        *,
        prefix: str | Sequence[str] = ".",
        case_sensitive: bool = False,
    ) -> None:
        self.names = {names} if isinstance(names, str) else set(names)
        self.prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
        self.case_sensitive = case_sensitive
        if not case_sensitive:
            self.names = {n.lower() for n in self.names}

    async def check(self, ctx: Context) -> bool:
        raw = ctx.text.strip()
        if not raw:
            return False

        matched_prefix = next((p for p in self.prefixes if raw.startswith(p)), None)
        if matched_prefix is None:
            return False

        body = raw[len(matched_prefix) :]
        if not body:
            return False

        parts = body.split(maxsplit=1)
        cmd_token = parts[0].split("@", 1)[0]
        lookup = cmd_token if self.case_sensitive else cmd_token.lower()
        if lookup not in self.names:
            return False

        ctx.command = cmd_token
        ctx.arg_str = parts[1] if len(parts) > 1 else ""
        ctx.args = ctx.arg_str.split() if ctx.arg_str else []
        return True


class RegexFilter(Filter):
    """Matches a regular expression and stores re.Match on ctx.match."""

    def __init__(self, pattern: str, flags: int = 0) -> None:
        self._compiled = re.compile(pattern, flags)

    async def check(self, ctx: Context) -> bool:
        m = self._compiled.search(ctx.text)
        if m is None:
            return False
        ctx.match = m
        return True


class StateFilter(Filter):
    """Matches the current FSM state against one or more targets (or '*' / ANY_STATE)."""

    def __init__(self, *targets: State | str | None) -> None:
        if not targets:
            targets = (None,)
        self.targets: tuple[str | None, ...] = tuple(
            t.name if isinstance(t, State) else t for t in targets
        )

    async def check(self, ctx: Context) -> bool:
        current = await ctx.state.get()
        if ANY_STATE in self.targets:
            return current is not None
        return current in self.targets


def command(
    names: str | Sequence[str],
    *,
    prefix: str | Sequence[str] = ".",
    case_sensitive: bool = False,
) -> CommandFilter:
    return CommandFilter(names, prefix=prefix, case_sensitive=case_sensitive)


def regex(pattern: str, flags: int = 0) -> RegexFilter:
    return RegexFilter(pattern, flags=flags)


def state(*targets: State | str | None) -> StateFilter:
    return StateFilter(*targets)


text: Filter = _PredicateFilter(lambda ctx: bool(ctx.text))
outgoing: Filter = _PredicateFilter(lambda ctx: ctx.is_outgoing)
incoming: Filter = _PredicateFilter(lambda ctx: not ctx.is_outgoing)
private: Filter = _PredicateFilter(lambda ctx: ctx.message.chat.type == "private")
group: Filter = _PredicateFilter(
    lambda ctx: ctx.message.chat.type in ("group", "supergroup")
)
reply: Filter = _PredicateFilter(lambda ctx: ctx.message.reply_to_id is not None)


class CallbackFilter(Filter):
    """Matches callback_query data by exact value or prefix."""

    def __init__(self, data: str | None = None, *, prefix: str | None = None) -> None:
        self.data = data
        self.prefix = prefix

    async def check(self, ctx: Context) -> bool:
        cb = ctx.callback_data
        if cb is None:
            return False
        if self.data is not None:
            return cb == self.data
        if self.prefix is not None:
            return cb.startswith(self.prefix)
        return True


def callback(data: str | None = None, *, prefix: str | None = None) -> CallbackFilter:
    return CallbackFilter(data, prefix=prefix)
