import asyncio
import tempfile
import unittest
from pathlib import Path

from shirdal import (
    Context,
    FSMStorage,
    MockAdapter,
    SQLiteStorage,
    SelfBot,
    State,
    StatesGroup,
    command,
    state,
)


class Wizard(StatesGroup):
    step1 = State()


class TestPhase6SQLiteStorage(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_satisfies_fsm_protocol_and_persists_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shirdal.db"

            # First bot session sets state & data
            storage1 = SQLiteStorage(db_path)
            self.assertIsInstance(storage1, FSMStorage)
            bot1 = SelfBot(MockAdapter(), use_uvloop=False, anti_flood=False, storage=storage1)

            @bot1.on(command("begin"))
            async def begin(ctx: Context) -> None:
                await ctx.state.set(Wizard.step1)
                await ctx.state.update(token="abc-123")

            serve1 = asyncio.create_task(bot1.serve())
            await asyncio.sleep(0.02)
            await bot1.raw_adapter.push_incoming(".begin", chat_id=10, sender_id=20)
            await asyncio.sleep(0.03)
            await bot1.stop()
            await serve1

            # Second bot session reads persisted state after restart
            storage2 = SQLiteStorage(db_path)
            bot2 = SelfBot(MockAdapter(), use_uvloop=False, anti_flood=False, storage=storage2)

            @bot2.on(state(Wizard.step1))
            async def finish(ctx: Context) -> None:
                data = await ctx.state.data()
                await ctx.reply(f"resumed:{data['token']}:{ctx.text}")
                await ctx.state.clear()

            serve2 = asyncio.create_task(bot2.serve())
            await asyncio.sleep(0.02)
            await bot2.raw_adapter.push_incoming("ok", chat_id=10, sender_id=20)
            await asyncio.sleep(0.03)

            self.assertEqual(bot2.raw_adapter.sent_messages[0].text, "resumed:abc-123:ok")
            self.assertIsNone(await storage2.get_state((10, 20)))

            await bot2.stop()
            await serve2

    async def test_chat_cache_and_ttl_expiration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cache.db"
            storage = SQLiteStorage(db_path)

            await storage.set_chat(
                1001,
                chat_type="supergroup",
                title="Shirdal Devs",
                username="shirdal_devs",
                ttl=0.05,
            )
            cached = await storage.get_chat(1001)
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached.title, "Shirdal Devs")

            await asyncio.sleep(0.07)
            expired = await storage.get_chat(1001)
            self.assertIsNone(expired)
            storage.close()
