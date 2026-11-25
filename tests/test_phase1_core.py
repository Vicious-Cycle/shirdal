import asyncio
import unittest

from shirdal import Context, MockAdapter, SelfBot, TransportAdapter


class TestPhase1Core(unittest.IsolatedAsyncioTestCase):
    async def test_mock_adapter_satisfies_protocol(self) -> None:
        adapter = MockAdapter()
        self.assertIsInstance(adapter, TransportAdapter)

    async def test_selfbot_receives_and_replies(self) -> None:
        adapter = MockAdapter()
        bot = SelfBot(adapter, use_uvloop=False)
        received: list[str] = []

        @bot.on_message
        async def handle(ctx: Context) -> None:
            received.append(ctx.text)
            if ctx.text == ".ping":
                await ctx.reply("pong!")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)

        await adapter.push_incoming(".ping", chat_id=42)
        await asyncio.sleep(0.05)

        await bot.stop()
        await serve_task

        self.assertEqual(received, [".ping"])
        self.assertEqual(len(adapter.sent_messages), 1)
        self.assertEqual(adapter.sent_messages[0].text, "pong!")
        self.assertEqual(adapter.sent_messages[0].chat.id, 42)
