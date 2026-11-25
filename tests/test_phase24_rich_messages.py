import asyncio
import unittest
from unittest.mock import patch

from shirdal import (
    BotAPIAdapter,
    Context,
    RichDraftStream,
    Shirdal,
    button,
    command,
    incoming,
    rich_blockquote,
    rich_buttons,
    rich_code,
    rich_details,
    rich_divider,
    rich_footer,
    rich_heading,
    rich_math,
    rich_message,
    rich_paragraph,
    rich_table,
    rich_thinking,
)


class TestPhase24RichMessages(unittest.IsolatedAsyncioTestCase):
    def test_rich_message_validation_and_block_builders(self) -> None:
        with self.assertRaises(ValueError):
            rich_message()
        with self.assertRaises(ValueError):
            rich_message(html="<b>Hi</b>", markdown="**Hi**")
        with self.assertRaises(ValueError):
            rich_heading("Too big", size=7)

        rm = rich_message(
            blocks=[
                rich_heading("گزارش فروش", size=1),
                rich_paragraph("خلاصه وضعیت امروز:"),
                rich_table(
                    [["پکیج ۱", "۱۲۰"], ["پکیج ۲", "۸۵"]],
                    headers=["محصول", "تعداد"],
                    caption="آمار روزانه",
                ),
                rich_details(
                    "جزئیات فنی",
                    [rich_code("print('ok')", language="python"), rich_math("E = mc^2")],
                    is_open=True,
                ),
                rich_blockquote("عالی بود", credit="سیستم", expandable=True),
                rich_divider(),
                rich_buttons(
                    [button("تایید", "ok", style="success"), button("حذف", "del", style="danger")],
                    align="center",
                ),
                rich_footer("Shirdal Bot"),
            ],
            is_rtl=True,
            skip_entity_detection=True,
        )

        self.assertTrue(rm["is_rtl"])
        self.assertTrue(rm["skip_entity_detection"])
        self.assertEqual(len(rm["blocks"]), 8)
        self.assertEqual(rm["blocks"][0], {"type": "heading", "text": "گزارش فروش", "size": 1})
        self.assertEqual(rm["blocks"][2]["type"], "table")
        self.assertEqual(rm["blocks"][2]["cells"][0][0], {"text": "محصول", "is_header": True})
        self.assertEqual(rm["blocks"][3]["type"], "details")
        self.assertTrue(rm["blocks"][3]["is_open"])
        self.assertEqual(rm["blocks"][4]["type"], "expandable_blockquote")
        self.assertEqual(rm["blocks"][6]["align"], "center")
        self.assertEqual(rich_thinking("در حال بررسی..."), {"type": "thinking", "text": "در حال بررسی..."})

    async def test_rich_message_send_stream_and_edit_end_to_end(self) -> None:
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
                                "message_id": 200,
                                "date": 1700000000,
                                "chat": {"id": 888, "type": "private"},
                                "from": {"id": 888, "first_name": "Nima"},
                                "text": "/report",
                            },
                        }
                    ]
                return []
            calls.append((method, dict(payload or {})))
            if method in ("sendRichMessage", "editMessageText"):
                return {
                    "message_id": 201,
                    "date": 1700000001,
                    "chat": {"id": 888, "type": "private"},
                    "from": {"id": 999, "is_bot": True},
                    "text": "",
                }
            return True

        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("report", prefix="/"))
        async def report_cmd(ctx: Context) -> None:
            async with ctx.stream_rich(draft_id=12, is_rtl=True, can_stop=True, min_interval=0.0) as s:
                self.assertIsInstance(s, RichDraftStream)
                await s.thinking("در حال تحلیل...")
                await s.write("<h1>گزارش</h1>")
                await s.write("<p>تکمیل شد.</p>")
            await ctx.reply_rich(markdown="# Done\n\n**All good!**", is_rtl=False)
            await adapter.edit_message(888, 201, rich_message=rich_message(html="<p>ویرایش شد</p>", is_rtl=True))

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task

        methods = [m for m, _ in calls]
        self.assertEqual(
            methods,
            [
                "sendRichMessageDraft",
                "sendRichMessageDraft",
                "sendRichMessageDraft",
                "sendRichMessage",
                "sendRichMessage",
                "editMessageText",
            ],
        )

        # Verify thinking draft
        self.assertEqual(calls[0][1]["draft_id"], 12)
        self.assertTrue(calls[0][1]["can_stop"])
        self.assertEqual(calls[0][1]["rich_message"]["blocks"], [{"type": "thinking", "text": "در حال تحلیل..."}])
        self.assertTrue(calls[0][1]["rich_message"]["is_rtl"])

        # Verify finalized streamed RichMessage
        self.assertEqual(calls[3][1]["rich_message"]["html"], "<h1>گزارش</h1><p>تکمیل شد.</p>")
        self.assertTrue(calls[3][1]["rich_message"]["is_rtl"])

        # Verify direct reply_rich with markdown
        self.assertEqual(calls[4][1]["rich_message"]["markdown"], "# Done\n\n**All good!**")
        self.assertFalse(calls[4][1]["rich_message"]["is_rtl"])

        # Verify edit_message with rich_message
        self.assertEqual(calls[5][1]["rich_message"], {"html": "<p>ویرایش شد</p>", "is_rtl": True})
