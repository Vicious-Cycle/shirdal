import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from shirdal import MockAdapter, SelfBot


class TestPhase4Plugins(unittest.IsolatedAsyncioTestCase):
    async def test_hot_reload_and_unload_without_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_file = Path(tmp) / "greeter.py"
            plugin_file.write_text(
                (
                    "from shirdal import Context, command\n"
                    "def setup(bot):\n"
                    "    @bot.on(command('hi'))\n"
                    "    async def hi(ctx: Context):\n"
                    "        await ctx.reply('v1')\n"
                ),
                encoding="utf-8",
            )

            raw = MockAdapter()
            bot = SelfBot(
                raw,
                use_uvloop=False,
                anti_flood=False,
                plugins_dir=tmp,
                hot_reload=True,
                reload_interval=0.04,
            )

            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.03)

            await raw.push_incoming(".hi", chat_id=1)
            await asyncio.sleep(0.03)
            self.assertEqual([m.text for m in raw.sent_messages], ["v1"])

            # Modify plugin on disk with bumped mtime_ns
            old_stat = plugin_file.stat()
            plugin_file.write_text(
                (
                    "from shirdal import Context, command\n"
                    "def setup(bot):\n"
                    "    @bot.on(command('hi'))\n"
                    "    async def hi(ctx: Context):\n"
                    "        await ctx.reply('v2')\n"
                ),
                encoding="utf-8",
            )
            os.utime(
                plugin_file,
                ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000),
            )

            await asyncio.sleep(0.1)
            self.assertTrue(raw.is_connected)

            await raw.push_incoming(".hi", chat_id=1)
            await asyncio.sleep(0.03)
            self.assertEqual([m.text for m in raw.sent_messages], ["v1", "v2"])

            # Delete plugin and verify route is unregistered
            plugin_file.unlink()
            await asyncio.sleep(0.1)
            await raw.push_incoming(".hi", chat_id=1)
            await asyncio.sleep(0.03)
            self.assertEqual([m.text for m in raw.sent_messages], ["v1", "v2"])

            await bot.stop()
            await serve_task
