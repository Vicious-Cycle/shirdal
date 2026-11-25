import asyncio
import tempfile
import unittest
from pathlib import Path

from shirdal import ChatRef, Context, MockAdapter, SQLiteStorage, SelfBot, command


class TestPhase14ModerationAndCache(unittest.IsolatedAsyncioTestCase):
    async def test_group_moderation_helpers(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)

        @bot.on(command("mod"))
        async def mod_handler(ctx: Context) -> None:
            await ctx.ban(7, until_date=9999)
            await ctx.mute(8)
            await ctx.kick(9)
            await ctx.unban(7)

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)
        await raw.push_incoming(".mod", chat_id=-1001, sender_id=1)
        await asyncio.sleep(0.04)

        self.assertEqual(raw.banned_users, [(-1001, 7, 9999)])
        self.assertEqual(raw.muted_users, [(-1001, 8, None)])
        self.assertEqual(raw.kicked_users, [(-1001, 9)])
        self.assertEqual(raw.unbanned_users, [(-1001, 7)])

        await bot.stop()
        await serve_task

    async def test_get_chat_uses_sqlite_cache_to_avoid_api_spam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "chat_cache.db")
            raw = MockAdapter()
            raw.chats[-10055] = ChatRef(id=-10055, type="supergroup", title="Shirdal HQ")
            bot = SelfBot(raw, use_uvloop=False, anti_flood=False, storage=storage)
            titles: list[str | None] = []

            @bot.on(command("info"))
            async def info_handler(ctx: Context) -> None:
                c = await ctx.get_chat()
                titles.append(c.title)

            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.02)

            await raw.push_incoming(".info", chat_id=-10055)
            await asyncio.sleep(0.03)
            await raw.push_incoming(".info", chat_id=-10055)
            await asyncio.sleep(0.03)

            self.assertEqual(titles, ["Shirdal HQ", "Shirdal HQ"])
            # Adapter get_chat must be called only once; second call hits SQLiteStorage cache
            self.assertEqual(raw.get_chat_calls, 1)

            await bot.stop()
            await serve_task
