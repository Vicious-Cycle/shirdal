from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

FSMKey = tuple[int, int]  # (chat_id, user_id)


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


class MemoryStorage:
    """Fast in-memory FSM storage keyed by (chat_id, user_id)."""

    def __init__(self) -> None:
        self._records: dict[FSMKey, _Record] = {}

    async def get_state(self, key: FSMKey) -> str | None:
        rec = self._records.get(key)
        return rec.state if rec else None

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        rec = self._records.setdefault(key, _Record())
        rec.state = state

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        rec = self._records.get(key)
        return dict(rec.data) if rec else {}

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        rec = self._records.setdefault(key, _Record())
        rec.data.update(kwargs)
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
