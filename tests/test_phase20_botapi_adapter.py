import asyncio
import json
import unittest
from unittest.mock import patch

from shirdal import (
    BotAPIAdapter,
    Context,
    EventType,
    FloodWaitError,
    SelfBot,
    Shirdal,
    TransportAdapter,
    command,
    incoming,
)


class TestPhase20BotAPIAdapter(unittest.IsolatedAsyncioTestCase):
    def test_botapi_adapter_satisfies_protocol(self) -> None:
        self.assertIs(SelfBot, Shirdal)
        adapter = BotAPIAdapter("123456:ABC-DEF")
        self.assertIsInstance(adapter, TransportAdapter)

    def test_429_maps_to_floodwait(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF")

        class FakeResp:
            status = 429

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "ok": False,
                        "error_code": 429,
                        "description": "Too Many Requests: retry after 7",
                        "parameters": {"retry_after": 7},
                    }
                ).encode("utf-8")

        class FakeConn:
            def request(self, *args: object, **kwargs: object) -> None:
                pass

            def getresponse(self) -> FakeResp:
                return FakeResp()

            def close(self) -> None:
                pass

        with self.assertRaises(FloodWaitError) as ctx:
            adapter._request_sync("sendMessage", {"chat_id": 1, "text": "hi"}, dedicated_conn=FakeConn())
        self.assertEqual(ctx.exception.seconds, 7.0)

    async def test_botapi_end_to_end_command_reply(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF", poll_timeout=1)
        sent_calls: list[tuple[str, dict[str, object]]] = []
        poll_count = 0

        def fake_request(method: str, payload=None, **_kwargs):
            nonlocal poll_count
            if method == "getMe":
                return {"id": 999, "is_bot": True, "username": "shirdal_test_bot"}
            if method == "getUpdates":
                poll_count += 1
                if poll_count == 1:
                    return [
                        {
                            "update_id": 10,
                            "message": {
                                "message_id": 50,
                                "date": 1700000000,
                                "chat": {"id": 777, "type": "private"},
                                "from": {"id": 777, "username": "ali", "first_name": "Ali"},
                                "text": "/start",
                            },
                        }
                    ]
                return []
            if method == "sendMessage":
                sent_calls.append((method, dict(payload or {})))
                return {
                    "message_id": 51,
                    "date": 1700000001,
                    "chat": {"id": 777, "type": "private"},
                    "from": {"id": 999, "username": "shirdal_test_bot"},
                    "text": (payload or {}).get("text", ""),
                }
            return {}

        bot = SelfBot(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("start", prefix="/"))
        async def start_handler(ctx: Context) -> None:
            await ctx.reply("Hello from native BotAPI!")

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task

        self.assertEqual(adapter.bot_id, 999)
        self.assertEqual(len(sent_calls), 1)
        self.assertEqual(sent_calls[0][1]["chat_id"], 777)
        self.assertEqual(sent_calls[0][1]["text"], "Hello from native BotAPI!")
        self.assertEqual(sent_calls[0][1]["reply_parameters"], {"message_id": 50})

    def test_normalize_edited_message(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF")
        upd = adapter._normalize_update(
            {
                "update_id": 2,
                "edited_message": {
                    "message_id": 12,
                    "date": 1700000000,
                    "chat": {"id": -1001, "type": "supergroup", "title": "Devs"},
                    "from": {"id": 42, "first_name": "Sara"},
                    "caption": "edited caption",
                    "photo": [{"file_id": "small"}, {"file_id": "large", "file_size": 2048}],
                },
            }
        )
        assert upd is not None
        self.assertEqual(upd.type, EventType.EDIT_MESSAGE)
        assert upd.message is not None
        self.assertEqual(upd.message.text, "edited caption")
        assert upd.message.media is not None
        self.assertEqual(upd.message.media.file_id, "large")
