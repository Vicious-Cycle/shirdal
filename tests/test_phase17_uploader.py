import asyncio
import unittest

from shirdal import (
    Context,
    MockAdapter,
    ProgressTracker,
    SelfBot,
    TransferProgress,
    TransferQueue,
    command,
)


class TestPhase17Uploader(unittest.IsolatedAsyncioTestCase):
    async def test_progress_tracker_throttles_updates(self) -> None:
        seen: list[TransferProgress] = []
        tracker = ProgressTracker(
            lambda p: seen.append(p),
            min_interval=10.0,
            min_percent_step=25.0,
        )

        # Simulate 100 chunks (1% each) -> only 0%, 25%, 50%, 75%, 100% should emit
        for i in range(1, 101):
            await tracker.report(i, 100)

        self.assertEqual(len(seen), 5)
        self.assertEqual(seen[-1].percent, 100.0)
        self.assertIn("100.0%", seen[-1].format_bar())

    async def test_reply_album_and_transfer_queue(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)
        queue = TransferQueue(max_concurrent=2)

        @bot.on(command("album"))
        async def album_handler(ctx: Context) -> None:
            msgs = await ctx.reply_album([b"a", b"b", b"c"], caption="3 files")
            self.assertEqual(len(msgs), 3)

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)
        await raw.push_incoming(".album", chat_id=88)
        await asyncio.sleep(0.04)

        self.assertEqual(len(raw.sent_albums), 1)
        self.assertEqual(raw.sent_albums[0][2], "3 files")

        async def _job() -> int:
            await asyncio.sleep(0.03)
            return 1

        results = await asyncio.gather(*(queue.run(_job) for _ in range(5)))
        self.assertEqual(sum(results), 5)
        self.assertLessEqual(queue.max_seen_active, 2)

        await bot.stop()
        await serve_task
