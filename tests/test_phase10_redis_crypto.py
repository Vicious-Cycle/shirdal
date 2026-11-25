import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from shirdal import (
    EncryptedStorage,
    FSMStorage,
    RedisStorage,
    SQLiteStorage,
    SecretBox,
)


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    async def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        val, exp = item
        if exp is not None and time.monotonic() >= exp:
            self._store.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: str, *, ex: float | None = None) -> None:
        exp = (time.monotonic() + ex) if ex is not None else None
        self._store[key] = (value, exp)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class TestPhase10RedisCrypto(unittest.IsolatedAsyncioTestCase):
    async def test_secret_box_roundtrip_and_tamper_detection(self) -> None:
        box = SecretBox("super-secret-key")
        token = box.encrypt(b"my-session-string")
        self.assertEqual(box.decrypt(token), b"my-session-string")

        tampered = ("A" if token[0] != "A" else "B") + token[1:]
        with self.assertRaises(ValueError):
            box.decrypt(tampered)

    async def test_encrypted_storage_hides_plaintext_in_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enc.db"
            raw_sqlite = SQLiteStorage(db_path)
            enc = EncryptedStorage(raw_sqlite, "shirdal-master-key")
            self.assertIsInstance(enc, FSMStorage)

            await enc.set_state((1, 2), "Auth:waiting_code")
            await enc.update_data((1, 2), phone="+989120000000")

            # Raw SQLite must NOT contain plaintext state or phone
            raw_state = await raw_sqlite.get_state((1, 2))
            raw_data = await raw_sqlite.get_data((1, 2))
            self.assertNotEqual(raw_state, "Auth:waiting_code")
            self.assertNotIn("phone", raw_data)

            # EncryptedStorage decrypts transparently
            self.assertEqual(await enc.get_state((1, 2)), "Auth:waiting_code")
            self.assertEqual((await enc.get_data((1, 2)))["phone"], "+989120000000")
            enc.close()

    async def test_redis_storage_fsm_and_chat_ttl(self) -> None:
        fake = _FakeAsyncRedis()
        storage = RedisStorage(client=fake)
        self.assertIsInstance(storage, FSMStorage)

        await storage.set_state((5, 9), "Step:one")
        await storage.update_data((5, 9), count=3)
        self.assertEqual(await storage.get_state((5, 9)), "Step:one")
        self.assertEqual((await storage.get_data((5, 9)))["count"], 3)
        await storage.clear((5, 9))
        self.assertIsNone(await storage.get_state((5, 9)))

        await storage.set_chat(55, title="VIP", ttl=0.05)  # type: ignore[arg-type]
        self.assertEqual((await storage.get_chat(55)).title, "VIP")  # type: ignore[union-attr]
        await asyncio.sleep(0.07)
        self.assertIsNone(await storage.get_chat(55))
