from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

FSMKey = tuple[int, int]  # (chat_id, user_id)
ANY_STATE = "*"


class FSMStrategy(str, Enum):
    """Keying strategy for FSM state isolation."""

    USER_IN_CHAT = "user_in_chat"
    CHAT = "chat"
    GLOBAL_USER = "global_user"
    USER_IN_TOPIC = "user_in_topic"


def resolve_fsm_key(
    strategy: FSMStrategy,
    chat_id: int,
    user_id: int,
    topic_id: int | None = None,
) -> FSMKey:
    if strategy == FSMStrategy.CHAT:
        return (chat_id, 0)
    if strategy == FSMStrategy.GLOBAL_USER:
        return (0, user_id)
    if strategy == FSMStrategy.USER_IN_TOPIC and topic_id is not None:
        return (chat_id ^ (topic_id << 20), user_id)
    return (chat_id, user_id)


@dataclass(slots=True, frozen=True)
class State:
    name: str | None = None

    def __str__(self) -> str:
        return self.name or ""


class _StatesGroupMeta(type):
    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
        cls = super().__new__(mcs, name, bases, namespace)
        for attr, val in namespace.items():
            if isinstance(val, State) and val.name is None:
                setattr(cls, attr, State(f"{name}:{attr}"))
        return cls


class StatesGroup(metaclass=_StatesGroupMeta):
    """Declarative container for multi-step conversation states."""


@runtime_checkable
class FSMStorage(Protocol):
    async def get_state(self, key: FSMKey) -> str | None: ...
    async def set_state(self, key: FSMKey, state: str | None) -> None: ...
    async def get_data(self, key: FSMKey) -> dict[str, Any]: ...
    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]: ...
    async def clear(self, key: FSMKey) -> None: ...


@dataclass(slots=True)
class _Record:
    state: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    expires_at: float | None = None


class MemoryStorage:
    """Fast in-memory FSM storage with optional per-key TTL expiration."""

    def __init__(self, *, ttl: float | None = None) -> None:
        self._records: dict[FSMKey, _Record] = {}
        self.ttl = ttl

    def _get_valid(self, key: FSMKey) -> _Record | None:
        rec = self._records.get(key)
        if rec is None:
            return None
        if rec.expires_at is not None and rec.expires_at <= time.monotonic():
            self._records.pop(key, None)
            return None
        return rec

    def _touch(self, rec: _Record) -> None:
        if self.ttl is not None:
            rec.expires_at = time.monotonic() + self.ttl

    async def get_state(self, key: FSMKey) -> str | None:
        rec = self._get_valid(key)
        return rec.state if rec else None

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        rec = self._get_valid(key)
        if rec is None:
            rec = _Record()
            self._records[key] = rec
        rec.state = state
        self._touch(rec)

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        rec = self._get_valid(key)
        return dict(rec.data) if rec else {}

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        rec = self._get_valid(key)
        if rec is None:
            rec = _Record()
            self._records[key] = rec
        rec.data.update(kwargs)
        self._touch(rec)
        return dict(rec.data)

    async def clear(self, key: FSMKey) -> None:
        self._records.pop(key, None)


class FSMContext:
    """Ergonomic state helper attached to ctx.state."""

    __slots__ = ("storage", "key")

    def __init__(self, storage: FSMStorage, key: FSMKey) -> None:
        self.storage = storage
        self.key = key

    async def get(self) -> str | None:
        return await self.storage.get_state(self.key)

    async def set(self, state: State | str | None) -> None:
        raw = state.name if isinstance(state, State) else state
        await self.storage.set_state(self.key, raw)

    async def data(self) -> dict[str, Any]:
        return await self.storage.get_data(self.key)

    async def update(self, **kwargs: Any) -> dict[str, Any]:
        return await self.storage.update_data(self.key, **kwargs)

    async def clear(self) -> None:
        await self.storage.clear(self.key)
