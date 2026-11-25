import asyncio
import time
import unittest

from shirdal import (
    AntiFloodAdapter,
    AntiFloodConfig,
    Context,
    FloodWaitError,
    MockAdapter,
    SelfBot,
    TransportAdapter,
    command,
)


class TestPhase3AntiFlood(unittest.IsolatedAsyncioTestCase):
    async def test_antiflood_satisfies_protocol(self) -> None:
        guarded = AntiFloodAdapter(MockAdapter())
        self.assertIsInstance(guarded, TransportAdapter)

    async def test_automatic_floodwait_recovery(self) -> None:
        raw = MockAdapter()
        raw.queue_flood_wait(0.03)
        raw.queue_flood_wait(0.02)

        cfg = AntiFloodConfig(
            per_chat_interval=0.0,
            max_wait_seconds=1.0,
            max_retries=3,
            safety_buffer=0.01,
        )
        bot = SelfBot(raw, use_uvloop=False, anti_flood=True, flood_config=cfg)

        @bot.on(command("burst"))
        async def burst_handler(ctx: Context) -> None:
            await ctx.reply("recovered!")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)
        await raw.push_incoming(".burst", chat_id=11)
        await asyncio.sleep(0.15)
        await bot.stop()
        await serve_task

        self.assertEqual(len(raw.sent_messages), 1)
        self.assertEqual(raw.sent_messages[0].text, "recovered!")
        assert isinstance(bot.adapter, AntiFloodAdapter)
        self.assertEqual(bot.adapter.stats.flood_waits_handled, 2)
        self.assertEqual(bot.adapter.stats.retries, 2)

    async def test_floodwait_exceeding_max_wait_raises(self) -> None:
        raw = MockAdapter()
        raw.queue_flood_wait(120.0)
        guarded = AntiFloodAdapter(
            raw,
            config=AntiFloodConfig(per_chat_interval=0.0, max_wait_seconds=5.0),
        )
        with self.assertRaises(FloodWaitError):
            await guarded.send_message(1, "blocked")

    async def test_per_chat_pacing_spaces_concurrent_bursts(self) -> None:
        raw = MockAdapter()
        guarded = AntiFloodAdapter(
            raw,
            config=AntiFloodConfig(per_chat_interval=0.05),
        )
        t0 = time.monotonic()
        await asyncio.gather(
            guarded.send_message(77, "m1"),
            guarded.send_message(77, "m2"),
            guarded.send_message(77, "m3"),
        )
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.09)
        self.assertEqual(len(raw.sent_messages), 3)
