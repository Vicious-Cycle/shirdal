import asyncio
import unittest

from shirdal import MockAdapter, SelfBot


class TestPhase9Scheduler(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_job_and_exception_isolation(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)
        ticks: list[int] = []

        @bot.every(seconds=0.03, run_immediately=True)
        async def heartbeat(b: SelfBot) -> None:
            ticks.append(len(ticks) + 1)
            if len(ticks) == 1:
                raise RuntimeError("transient glitch")
            await b.adapter.send_message(1, f"tick:{len(ticks)}")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.11)
        await bot.stop()
        await serve_task

        self.assertGreaterEqual(len(ticks), 3)
        self.assertGreaterEqual(len(raw.sent_messages), 2)
        self.assertEqual(raw.sent_messages[0].text, "tick:2")

    async def test_plugin_unregister_cancels_scheduled_jobs(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)

        bot._active_plugin_scope = "clock"

        @bot.every(seconds=0.02, run_immediately=True)
        async def tick() -> None:
            await raw.send_message(1, "clock")

        bot._active_plugin_scope = None
        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.05)

        removed = bot.scheduler.unregister_plugin("clock")
        self.assertEqual(removed, 1)
        count_at_remove = len(raw.sent_messages)

        await asyncio.sleep(0.06)
        self.assertEqual(len(raw.sent_messages), count_at_remove)

        await bot.stop()
        await serve_task
