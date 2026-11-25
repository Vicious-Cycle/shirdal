from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from shirdal.engine.fsm import FSMKey
from shirdal.storage.base import CachedChat


class SQLiteStorage:
    """Tuned WAL-mode SQLite storage with L1 in-memory cache for FSM and chats."""

    def __init__(self, db_path: str | Path = "shirdal.db") -> None:
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._apply_pragmas()
        self._init_schema()

        self._fsm_cache: dict[FSMKey, tuple[str | None, dict[str, Any]]] = {}
        self._chat_cache: dict[int, CachedChat] = {}

    def _apply_pragmas(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA cache_size=-32000;")
        self._conn.execute("PRAGMA mmap_size=268435456;")

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_states (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    state TEXT,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_cache (
                    chat_id INTEGER PRIMARY KEY,
                    chat_type TEXT NOT NULL,
                    title TEXT,
                    username TEXT,
                    extra TEXT,
                    expires_at REAL
                )
                """
            )

    def _load_fsm_row(self, key: FSMKey) -> tuple[str | None, dict[str, Any]]:
        cached = self._fsm_cache.get(key)
        if cached is not None:
            return cached[0], dict(cached[1])

        cur = self._conn.execute(
            "SELECT state, data FROM fsm_states WHERE chat_id = ? AND user_id = ?",
            (key[0], key[1]),
        )
        row = cur.fetchone()
        if row is None:
            return None, {}
        state_val = row[0]
        data_val = json.loads(row[1]) if row[1] else {}
        self._fsm_cache[key] = (state_val, dict(data_val))
        return state_val, data_val

    def _upsert_fsm_row(
        self, key: FSMKey, state_val: str | None, data_val: dict[str, Any]
    ) -> None:
        payload = json.dumps(data_val, ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO fsm_states (chat_id, user_id, state, data, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    state = excluded.state,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (key[0], key[1], state_val, payload, time.time()),
            )
        self._fsm_cache[key] = (state_val, dict(data_val))

    async def get_state(self, key: FSMKey) -> str | None:
        async with self._lock:
            state_val, _ = self._load_fsm_row(key)
            return state_val

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        async with self._lock:
            _, data_val = self._load_fsm_row(key)
            self._upsert_fsm_row(key, state, data_val)

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        async with self._lock:
            _, data_val = self._load_fsm_row(key)
            return data_val

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        async with self._lock:
            state_val, data_val = self._load_fsm_row(key)
            data_val.update(kwargs)
            self._upsert_fsm_row(key, state_val, data_val)
            return dict(data_val)

    async def clear(self, key: FSMKey) -> None:
        async with self._lock:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM fsm_states WHERE chat_id = ? AND user_id = ?",
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
        async with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO chat_cache (chat_id, chat_type, title, username, extra, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        chat_type = excluded.chat_type,
                        title = excluded.title,
                        username = excluded.username,
                        extra = excluded.extra,
                        expires_at = excluded.expires_at
                    """,
                    (chat_id, chat_type, title, username, extra_json, expires_at),
                )
            self._chat_cache[chat_id] = record
        return record

    async def get_chat(self, chat_id: int) -> CachedChat | None:
        now = time.time()
        async with self._lock:
            cached = self._chat_cache.get(chat_id)
            if cached is not None:
                if cached.expires_at is None or cached.expires_at > now:
                    return cached
                self._chat_cache.pop(chat_id, None)

            cur = self._conn.execute(
                "SELECT chat_id, chat_type, title, username, extra, expires_at FROM chat_cache WHERE chat_id = ?",
                (chat_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None

            expires_at = row[5]
            if expires_at is not None and expires_at <= now:
                with self._conn:
                    self._conn.execute("DELETE FROM chat_cache WHERE chat_id = ?", (chat_id,))
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
        async with self._lock:
            self._chat_cache.pop(chat_id, None)
            with self._conn:
                self._conn.execute("DELETE FROM chat_cache WHERE chat_id = ?", (chat_id,))

    def close(self) -> None:
        self._conn.close()
