from __future__ import annotations

import json
from typing import Any

from shirdal.engine.fsm import FSMKey
from shirdal.storage.base import CachedChat


class RedisStorage:
    """Distributed Redis backend for FSM states and chat caching."""

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        prefix: str = "shirdal:",
        client: Any = None,
    ) -> None:
        self.prefix = prefix
        if client is not None:
            self._redis = client
        else:
            try:
                import redis.asyncio as aioredis  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "Redis is not installed. Run: pip install 'shirdal[redis]'"
                ) from exc
            self._redis = aioredis.from_url(url, decode_responses=True)

    def _fsm_key(self, key: FSMKey) -> str:
        return f"{self.prefix}fsm:{key[0]}:{key[1]}"

    def _chat_key(self, chat_id: int) -> str:
        return f"{self.prefix}chat:{chat_id}"

    async def _load_fsm(self, key: FSMKey) -> dict[str, Any]:
        raw = await self._redis.get(self._fsm_key(key))
        if not raw:
            return {"state": None, "data": {}}
        return json.loads(raw)

    async def _save_fsm(self, key: FSMKey, payload: dict[str, Any]) -> None:
        await self._redis.set(
            self._fsm_key(key), json.dumps(payload, ensure_ascii=False)
        )

    async def get_state(self, key: FSMKey) -> str | None:
        payload = await self._load_fsm(key)
        return payload.get("state")

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        payload = await self._load_fsm(key)
        payload["state"] = state
        await self._save_fsm(key, payload)

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        payload = await self._load_fsm(key)
        return dict(payload.get("data", {}))

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        payload = await self._load_fsm(key)
        data = dict(payload.get("data", {}))
        data.update(kwargs)
        payload["data"] = data
        await self._save_fsm(key, payload)
        return data

    async def clear(self, key: FSMKey) -> None:
        await self._redis.delete(self._fsm_key(key))

    async def set_chat(
        self,
        chat_id: int,
        *,
        chat_type: str = "private",
        title: str | None = None,
        username: str | None = None,
        extra: dict[str, Any] | None = None,
        ttl: int | None = None,
    ) -> CachedChat:
        record = CachedChat(
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            username=username,
            extra=extra,
        )
        raw = json.dumps(
            {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "title": title,
                "username": username,
                "extra": extra,
            },
            ensure_ascii=False,
        )
        await self._redis.set(self._chat_key(chat_id), raw, ex=ttl)
        return record

    async def get_chat(self, chat_id: int) -> CachedChat | None:
        raw = await self._redis.get(self._chat_key(chat_id))
        if not raw:
            return None
        d = json.loads(raw)
        return CachedChat(
            chat_id=d["chat_id"],
            chat_type=d["chat_type"],
            title=d.get("title"),
            username=d.get("username"),
            extra=d.get("extra"),
        )

    async def invalidate_chat(self, chat_id: int) -> None:
        await self._redis.delete(self._chat_key(chat_id))
