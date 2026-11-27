from __future__ import annotations

import asyncio
import os
import stat
import sys

import pytest

from shirdal.mtproto.updates import PeerCache
from shirdal.storage.sqlite import SQLiteStorage


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_secret_dbs_are_owner_only(tmp_path):
    db = tmp_path / "peers.db"
    PeerCache(db)
    assert _mode(db) == 0o600

    st = tmp_path / "state.db"
    storage = SQLiteStorage(st)
    try:
        assert _mode(st) == 0o600
    finally:
        storage.close()


def test_peercache_skips_unchanged_writes(tmp_path):
    cache = PeerCache(tmp_path / "p.db")
    cache.put("user", 1, 111, "bob")
    writes = []
    import sqlite3

    real = sqlite3.connect

    def spy(*a, **k):
        writes.append(a)
        return real(*a, **k)

    sqlite3.connect = spy  # type: ignore[assignment]
    try:
        cache.put("user", 1, 111, "bob")  # identical -> no DB hit
        assert writes == []
        cache.put("user", 1, 222, "bob")  # changed -> persisted
        assert len(writes) == 1
    finally:
        sqlite3.connect = real  # type: ignore[assignment]
    assert PeerCache(tmp_path / "p.db").get("user", 1).access_hash == 222


def test_sqlite_storage_roundtrip_in_threads(tmp_path):
    async def run() -> None:
        s = SQLiteStorage(tmp_path / "s.db")
        key = (1, 2)
        await asyncio.gather(*(s.update_data(key, **{f"k{i}": i}) for i in range(20)))
        data = await s.get_data(key)
        assert data == {f"k{i}": i for i in range(20)}
        await s.set_state(key, "waiting")
        s.close()
        s2 = SQLiteStorage(tmp_path / "s.db")  # persisted, not just cached
        assert await s2.get_state(key) == "waiting"
        await s2.set_chat(5, title="t", ttl=60)
        s2._chat_cache.clear()
        assert (await s2.get_chat(5)).title == "t"
        await s2.invalidate_chat(5)
        assert await s2.get_chat(5) is None
        await s2.clear(key)
        s2._fsm_cache.clear()
        assert await s2.get_state(key) is None
        s2.close()

    asyncio.run(run())


def test_gap_during_running_sync_triggers_rerun():
    """A pts gap seen while getDifference is in flight must cause one more sync, not be lost."""
    import os

    from shirdal import NativeMTProtoAdapter

    async def run() -> None:
        ad = NativeMTProtoAdapter(1, "h", auth_key=os.urandom(256))
        ad.updates.pts = 10
        calls = 0
        gate = asyncio.Event()

        async def fake_once() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                await gate.wait()

        ad._sync_updates_once = fake_once  # type: ignore[method-assign]
        first = asyncio.create_task(ad.sync_updates_state())
        await asyncio.sleep(0)
        await ad.sync_updates_state()  # requested while the first is running
        gate.set()
        await first
        assert calls == 2

    asyncio.run(run())
