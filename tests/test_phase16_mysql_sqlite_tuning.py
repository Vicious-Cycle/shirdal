import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from shirdal import FSMStorage, MySQLStorage, SQLiteStorage


class _FakeMySQLCursor:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self._last_cur: sqlite3.Cursor | None = None

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        q = query.strip()
        if q.upper().startswith("CREATE TABLE"):
            return
        # Translate MySQL %s placeholders and ON DUPLICATE KEY UPDATE for in-memory test
        if "ON DUPLICATE KEY UPDATE" in q and "shirdal_fsm" in q:
            self._db.execute(
                "INSERT OR REPLACE INTO shirdal_fsm (chat_id, user_id, state, data, updated_at) VALUES (?, ?, ?, ?, ?)",
                params,
            )
            return
        if "ON DUPLICATE KEY UPDATE" in q and "shirdal_chat_cache" in q:
            self._db.execute(
                "INSERT OR REPLACE INTO shirdal_chat_cache (chat_id, chat_type, title, username, extra, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                params,
            )
            return
        self._last_cur = self._db.execute(q.replace("%s", "?"), params)

    async def fetchone(self) -> Any:
        return self._last_cur.fetchone() if self._last_cur else None


class _FakeMySQLConn:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    @asynccontextmanager
    async def cursor(self):
        yield _FakeMySQLCursor(self._db)


class _FakeMySQLPool:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE shirdal_fsm (chat_id INT, user_id INT, state TEXT, data TEXT, updated_at REAL, PRIMARY KEY (chat_id, user_id))"
        )
        self.db.execute(
            "CREATE TABLE shirdal_chat_cache (chat_id INT PRIMARY KEY, chat_type TEXT, title TEXT, username TEXT, extra TEXT, expires_at REAL)"
        )

    @asynccontextmanager
    async def acquire(self):
        yield _FakeMySQLConn(self.db)

    def close(self) -> None:
        self.db.close()

    async def wait_closed(self) -> None:
        pass


class TestPhase16MySQLAndSQLiteTuning(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_wal_tuning_pragmas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "tuned.db")
            mode = storage._conn.execute("PRAGMA journal_mode;").fetchone()[0]
            busy = storage._conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            temp_store = storage._conn.execute("PRAGMA temp_store;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
            self.assertEqual(busy, 5000)
            self.assertEqual(temp_store, 2)  # 2 = MEMORY
            storage.close()

    async def test_mysql_storage_fsm_and_chat_cache(self) -> None:
        pool = _FakeMySQLPool()
        storage = MySQLStorage(pool=pool)
        self.assertIsInstance(storage, FSMStorage)

        await storage.set_state((10, 20), "Setup:step1")
        await storage.update_data((10, 20), lang="fa")
        self.assertEqual(await storage.get_state((10, 20)), "Setup:step1")
        self.assertEqual((await storage.get_data((10, 20)))["lang"], "fa")
        await storage.clear((10, 20))
        self.assertIsNone(await storage.get_state((10, 20)))

        await storage.set_chat(99, title="MySQL Group", ttl=0.05)
        self.assertEqual((await storage.get_chat(99)).title, "MySQL Group")  # type: ignore[union-attr]
        await asyncio.sleep(0.07)
        self.assertIsNone(await storage.get_chat(99))
        await storage.aclose()
