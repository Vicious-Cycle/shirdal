import asyncio
import logging
import unittest
from pathlib import Path

from shirdal import Context, EventType, MockAdapter, SelfBot, command


class TestPhase13Polish(unittest.IsolatedAsyncioTestCase):
    def test_py_typed_marker_exists(self) -> None:
        pkg_root = Path(__file__).resolve().parent.parent / "src" / "shirdal"
        self.assertTrue((pkg_root / "py.typed").exists())

    async def test_on_error_and_on_edit_handlers(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)
        errors: list[str] = []
        edited: list[str] = []

        @bot.on(command("boom"))
        async def boom(ctx: Context) -> None:
            raise ValueError("kaboom")

        @bot.on_error
        async def handle_err(ctx: Context, exc: Exception) -> None:
            errors.append(f"{ctx.command}:{exc}")
            await ctx.reply(f"Error caught: {exc}")

        @bot.on_edit()
        async def handle_edit(ctx: Context) -> None:
            edited.append(ctx.text)

        logging.disable(logging.CRITICAL)
        try:
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.02)

            await raw.push_incoming(".boom", chat_id=3)
            await raw.push_incoming("updated text", chat_id=3, event_type=EventType.EDIT_MESSAGE)
            await asyncio.sleep(0.05)

            self.assertEqual(errors, ["boom:kaboom"])
            self.assertEqual(raw.sent_messages[0].text, "Error caught: kaboom")
            self.assertEqual(edited, ["updated text"])

            await bot.stop()
            await serve_task
        finally:
            logging.disable(logging.NOTSET)
