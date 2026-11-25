from __future__ import annotations

import json
import time
from typing import Any

from shirdal.engine.fsm import FSMKey
from shirdal.storage.base import CachedChat


class MySQLStorage:
    """Async MySQL storage backend (aiomysql pool) with L1 cache for FSM and chats."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        db: str = "shirdal",
        minsize: int = 1,
        maxsize: int = 10,
        pool: Any = None,
    ) -> None:
        self._dsn = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "db": db,
            "minsize": minsize,
            "maxsize": maxsize,
            "autocommit": True,
        }
        self._pool = pool
        self._fsm_cache: dict[FSMKey, tuple[str | None, dict[str, Any]]] = {}
        self._chat_cache: dict[int, CachedChat] = {}

    async def connect(self) -> None:
        if self._pool is None:
            try:
                import aiomysql  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "aiomysql is not installed. Run: pip install 'shirdal[mysql]'"
                ) from exc
            self._pool = await aiomysql.create_pool(**self._dsn)
        await self._init_schema()

    async def _execute(
        self, query: str, params: tuple[Any, ...] = (), *, fetchone: bool = False
    ) -> Any:
        if self._pool is None:
            await self.connect()
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                if fetchone:
                    return await cur.fetchone()
                return None

    async def _init_schema(self) -> None:
        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS shirdal_fsm (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                state VARCHAR(255),
                data TEXT NOT NULL,
                updated_at DOUBLE NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS shirdal_chat_cache (
                chat_id BIGINT PRIMARY KEY,
                chat_type VARCHAR(32) NOT NULL,
                title VARCHAR(255),
                username VARCHAR(255),
                extra TEXT,
                expires_at DOUBLE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

    async def _load_fsm(self, key: FSMKey) -> tuple[str | None, dict[str, Any]]:
        cached = self._fsm_cache.get(key)
        if cached is not None:
            return cached[0], dict(cached[1])
        row = await self._execute(
            "SELECT state, data FROM shirdal_fsm WHERE chat_id = %s AND user_id = %s",
            (key[0], key[1]),
            fetchone=True,
        )
        if row is None:
            return None, {}
        state_val = row[0]
        data_val = json.loads(row[1]) if row[1] else {}
        self._fsm_cache[key] = (state_val, dict(data_val))
        return state_val, data_val

    async def _upsert_fsm(
        self, key: FSMKey, state_val: str | None, data_val: dict[str, Any]
    ) -> None:
        payload = json.dumps(data_val, ensure_ascii=False)
        await self._execute(
            """
            INSERT INTO shirdal_fsm (chat_id, user_id, state, data, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                state = VALUES(state),
                data = VALUES(data),
                updated_at = VALUES(updated_at)
            """,
            (key[0], key[1], state_val, payload, time.time()),
        )
        self._fsm_cache[key] = (state_val, dict(data_val))

    async def get_state(self, key: FSMKey) -> str | None:
        state_val, _ = await self._load_fsm(key)
        return state_val

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        _, data_val = await self._load_fsm(key)
        await self._upsert_fsm(key, state, data_val)

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        _, data_val = await self._load_fsm(key)
        return data_val

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        state_val, data_val = await self._load_fsm(key)
        data_val.update(kwargs)
        await self._upsert_fsm(key, state_val, data_val)
        return dict(data_val)

    async def clear(self, key: FSMKey) -> None:
        await self._execute(
            "DELETE FROM shirdal_fsm WHERE chat_id = %s AND user_id = %s",
            (key[0], key[1]),
        )
        self._fsm_cache.pop(key, None)

    async def set_chat(
        self,
        chat_id: int,
        *,
        chat_type: str = "private",
        title: str | None = None,
        username: str | None = None,
        extra: dict[str, Any] | None = None,
        ttl: float | None = None,
    ) -> CachedChat:
        expires_at = (time.time() + ttl) if ttl is not None else None
        record = CachedChat(
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            username=username,
            extra=extra,
            expires_at=expires_at,
        )
        extra_json = json.dumps(extra, ensure_ascii=False) if extra is not None else None
        await self._execute(
            """
            INSERT INTO shirdal_chat_cache (chat_id, chat_type, title, username, extra, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                chat_type = VALUES(chat_type),
                title = VALUES(title),
                username = VALUES(username),
                extra = VALUES(extra),
                expires_at = VALUES(expires_at)
            """,
            (chat_id, chat_type, title, username, extra_json, expires_at),
        )
        self._chat_cache[chat_id] = record
        return record

    async def get_chat(self, chat_id: int) -> CachedChat | None:
        now = time.time()
        cached = self._chat_cache.get(chat_id)
        if cached is not None:
            if cached.expires_at is None or cached.expires_at > now:
                return cached
            self._chat_cache.pop(chat_id, None)

        row = await self._execute(
            "SELECT chat_id, chat_type, title, username, extra, expires_at FROM shirdal_chat_cache WHERE chat_id = %s",
            (chat_id,),
            fetchone=True,
        )
        if row is None:
            return None
        expires_at = row[5]
        if expires_at is not None and expires_at <= now:
            await self._execute("DELETE FROM shirdal_chat_cache WHERE chat_id = %s", (chat_id,))
            return None
        record = CachedChat(
            chat_id=row[0],
            chat_type=row[1],
            title=row[2],
            username=row[3],
            extra=json.loads(row[4]) if row[4] else None,
            expires_at=expires_at,
        )
        self._chat_cache[chat_id] = record
        return record

    async def invalidate_chat(self, chat_id: int) -> None:
        self._chat_cache.pop(chat_id, None)
        await self._execute("DELETE FROM shirdal_chat_cache WHERE chat_id = %s", (chat_id,))

    async def aclose(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
