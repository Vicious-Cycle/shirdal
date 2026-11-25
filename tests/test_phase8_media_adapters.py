import asyncio
import tempfile
import unittest
from pathlib import Path

from shirdal import (
    AdapterError,
    AntiFloodConfig,
    ChatAction,
    Context,
    HydrogramAdapter,
    MediaRef,
    MockAdapter,
    SelfBot,
    TelethonAdapter,
    command,
)


class TestPhase8MediaAdapters(unittest.IsolatedAsyncioTestCase):
    async def test_media_reply_download_react_pin_and_typing(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(
            raw,
            use_uvloop=False,
            anti_flood=True,
            flood_config=AntiFloodConfig(per_chat_interval=0.01),
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "saved.bin"

            @bot.on(command("save"))
            async def save_handler(ctx: Context) -> None:
                async with ctx.typing(ChatAction.UPLOAD_DOCUMENT, interval=0.05):
                    await ctx.react("🔥")
                    await ctx.pin(silent=True)
                    if ctx.has_media:
                        saved = await ctx.download(out_file)
                        self.assertEqual(saved, out_file)
                    await ctx.reply_media(b"123", caption="done!")

            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.02)

            await raw.push_incoming(
                ".save",
                chat_id=55,
                media=MediaRef(media_type="document", file_name="doc.pdf"),
            )
            await asyncio.sleep(0.08)

            self.assertTrue(out_file.exists())
            self.assertEqual(out_file.read_bytes(), b"SHIRDAL_MOCK_MEDIA")
            self.assertEqual(raw.reactions, [(55, 101, "🔥")])
            self.assertEqual(raw.pinned_messages, [(55, 101, True)])
            self.assertGreaterEqual(len(raw.chat_actions), 1)
            self.assertEqual(raw.chat_actions[0][1], "upload_document")
            self.assertEqual(raw.sent_media[0][2], "done!")

            await bot.stop()
            await serve_task

    async def test_lazy_adapter_imports_raise_helpful_error_when_missing(self) -> None:
        with self.assertRaises(AdapterError):
            TelethonAdapter("s", 123, "hash")
        with self.assertRaises(AdapterError):
            HydrogramAdapter("s", 123, "hash")
