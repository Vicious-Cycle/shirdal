import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shirdal import (
    BotAPIAdapter,
    Context,
    Shirdal,
    button,
    callback,
    command,
    incoming,
    inline_keyboard,
)
from shirdal.cli import main as cli_main


class TestPhase21CallbacksAndCLI(unittest.IsolatedAsyncioTestCase):
    def test_inline_keyboard_and_button_builders(self) -> None:
        kb = inline_keyboard([
            [button("Yes", "cb:yes"), button("Docs", url="https://example.com")],
        ])
        self.assertEqual(
            kb,
            {
                "inline_keyboard": [
                    [
                        {"text": "Yes", "callback_data": "cb:yes"},
                        {"text": "Docs", "url": "https://example.com"},
                    ]
                ]
            },
        )

    async def test_callback_query_flow_and_reply_markup(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF", poll_timeout=1)
        calls: list[tuple[str, dict[str, object]]] = []
        poll_idx = 0

        def fake_request(method: str, payload=None, **_kwargs):
            nonlocal poll_idx
            if method == "getMe":
                return {"id": 999, "is_bot": True, "username": "shirdal_bot"}
            if method == "getUpdates":
                poll_idx += 1
                if poll_idx == 1:
                    return [
                        {
                            "update_id": 1,
                            "message": {
                                "message_id": 10,
                                "date": 1700000000,
                                "chat": {"id": 555, "type": "private"},
                                "from": {"id": 555, "first_name": "Ali"},
                                "text": "/start",
                            },
                        },
                        {
                            "update_id": 2,
                            "callback_query": {
                                "id": "cbq_1",
                                "from": {"id": 555, "first_name": "Ali"},
                                "message": {
                                    "message_id": 11,
                                    "date": 1700000001,
                                    "chat": {"id": 555, "type": "private"},
                                },
                                "data": "btn:go",
                            },
                        },
                    ]
                return []
            calls.append((method, dict(payload or {})))
            if method in ("sendMessage", "editMessageText"):
                return {
                    "message_id": 11,
                    "date": 1700000002,
                    "chat": {"id": 555, "type": "private"},
                    "from": {"id": 999, "is_bot": True},
                    "text": (payload or {}).get("text", ""),
                }
            return True

        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("start", prefix="/"))
        async def start_cmd(ctx: Context) -> None:
            await ctx.reply("Choose:", reply_markup=inline_keyboard([[button("Go", "btn:go")]]))

        @bot.on_callback(callback(prefix="btn:"))
        async def on_btn(ctx: Context) -> None:
            await ctx.answer("Done!", show_alert=True)
            await ctx.edit(f"Clicked: {ctx.callback_data}")

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task

        methods = [m for m, _ in calls]
        self.assertIn("sendMessage", methods)
        self.assertIn("answerCallbackQuery", methods)
        self.assertIn("editMessageText", methods)
        send_payload = next(p for m, p in calls if m == "sendMessage")
        self.assertIn("reply_markup", send_payload)
        ans_payload = next(p for m, p in calls if m == "answerCallbackQuery")
        self.assertEqual(ans_payload["callback_query_id"], "cbq_1")
        self.assertEqual(ans_payload["text"], "Done!")
        self.assertTrue(ans_payload["show_alert"])

    def test_cli_new_botapi_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = cli_main(["new", "my_bot", "--adapter", "botapi", "--dir", tmp])
            self.assertEqual(code, 0)
            proj = Path(tmp) / "my_bot"
            main_py = (proj / "main.py").read_text(encoding="utf-8")
            self.assertIn("BotAPIAdapter", main_py)
            self.assertIn("Shirdal(", main_py)
            env_txt = (proj / ".env.example").read_text(encoding="utf-8")
            self.assertIn("BOT_TOKEN=", env_txt)
