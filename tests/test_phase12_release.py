import ast
import asyncio
import unittest
from pathlib import Path

import shirdal
from shirdal import AntiFloodConfig, MockAdapter, SelfBot

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "quickstart_selfbot"


class TestPhase12Release(unittest.IsolatedAsyncioTestCase):
    def test_version_is_1_0_0_and_examples_parse(self) -> None:
        self.assertEqual(shirdal.__version__, "1.1.0")
        for py_file in EXAMPLES_DIR.rglob("*.py"):
            ast.parse(py_file.read_text(encoding="utf-8"))

    async def test_example_plugins_load_and_run(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(
            raw,
            use_uvloop=False,
            anti_flood=True,
            flood_config=AntiFloodConfig(per_chat_interval=0.01),
            plugins_dir=EXAMPLES_DIR / "plugins",
            hot_reload=False,
        )

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.03)

        assert bot.plugins is not None
        self.assertEqual(
            sorted(bot.plugins.loaded_plugins),
            ["auto_clock", "essentials", "wizard"],
        )

        await raw.push_incoming(".ping", chat_id=1, is_outgoing=True)
        await raw.push_incoming(".stats", chat_id=1, is_outgoing=True)
        await asyncio.sleep(0.08)

        edited_texts = [m.text for m in raw.edited_messages]
        self.assertIn(f"🏓 Pong! Shirdal v{shirdal.__version__}", edited_texts)
        self.assertTrue(any(t.startswith("📊 Requests:") for t in edited_texts))

        await bot.stop()
        await serve_task
