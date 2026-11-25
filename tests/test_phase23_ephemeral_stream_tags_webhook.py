import asyncio
import json
import unittest
from unittest.mock import patch

from shirdal import (
    BotAPIAdapter,
    Context,
    DraftStream,
    Shirdal,
    WebhookServer,
    command,
    date_time,
    date_time_entity,
    incoming,
)


async def _send_raw_http(
    port: int,
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hdrs = {"Host": f"127.0.0.1:{port}", "Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    head_lines = [f"{method} {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in hdrs.items()]
    raw_req = ("\r\n".join(head_lines) + "\r\n\r\n").encode("ascii") + body
    writer.write(raw_req)
    await writer.drain()
    raw_resp = await reader.read()
    writer.close()
    await writer.wait_closed()
    head_part, _, body_part = raw_resp.partition(b"\r\n\r\n")
    status_line = head_part.decode("latin-1").split("\r\n")[0]
    status_code = int(status_line.split()[1])
    return status_code, json.loads(body_part.decode("utf-8"))


class TestPhase23EphemeralStreamTagsWebhook(unittest.IsolatedAsyncioTestCase):
    def test_date_time_helpers(self) -> None:
        tag = date_time(1764100000, "Tomorrow", format="r")
        self.assertEqual(tag, '<tg-time unix="1764100000" format="r">Tomorrow</tg-time>')
        tag_plain = date_time(1764100000)
        self.assertEqual(tag_plain, '<tg-time unix="1764100000">1764100000</tg-time>')
        ent = date_time_entity(0, 8, 1764100000, format="wDT")
        self.assertEqual(
            ent,
            {
                "type": "date_time",
                "offset": 0,
                "length": 8,
                "unix_time": 1764100000,
                "date_time_format": "wDT",
            },
        )

    async def test_ephemeral_messages_and_ai_draft_streaming(self) -> None:
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
                                "message_id": 100,
                                "date": 1700000000,
                                "chat": {"id": -100500, "type": "supergroup", "title": "Devs"},
                                "from": {"id": 777, "first_name": "Ali"},
                                "text": "/ask",
                            },
                        }
                    ]
                return []
            calls.append((method, dict(payload or {})))
            if method in ("sendMessage", "editEphemeralMessageText"):
                return {
                    "message_id": 101,
                    "ephemeral_message_id": 888,
                    "date": 1700000001,
                    "chat": {"id": -100500, "type": "supergroup"},
                    "from": {"id": 999, "is_bot": True},
                    "text": (payload or {}).get("text", ""),
                }
            return True

        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("ask", prefix="/"))
        async def ask_cmd(ctx: Context) -> None:
            await ctx.reply_ephemeral("Only you can see this!")
            async with ctx.stream(draft_id=7, can_stop=True, min_interval=0.0) as s:
                self.assertIsInstance(s, DraftStream)
                await s.write("Hello ")
                await s.write("World!")
            await ctx.set_member_tag("VIP")

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task

        methods = [m for m, _ in calls]
        self.assertEqual(
            methods,
            ["sendMessage", "sendMessageDraft", "sendMessageDraft", "sendMessage", "setChatMemberTag"],
        )

        eph_payload = calls[0][1]
        self.assertEqual(
            eph_payload["ephemeral_message_parameters"],
            {"receiver_user_id": 777},
        )

        draft1 = calls[1][1]
        self.assertEqual(draft1["draft_id"], 7)
        self.assertEqual(draft1["text"], "Hello ")
        self.assertTrue(draft1["can_stop"])

        draft2 = calls[2][1]
        self.assertEqual(draft2["text"], "Hello World!")

        final_msg = calls[3][1]
        self.assertEqual(final_msg["text"], "Hello World!")

        tag_payload = calls[4][1]
        self.assertEqual(tag_payload, {"chat_id": -100500, "user_id": 777, "tag": "VIP"})

    async def test_topics_settings_and_ephemeral_edit_delete(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF", poll_timeout=1)
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_request(method: str, payload=None, **_kwargs):
            calls.append((method, dict(payload or {})))
            if method == "createForumTopic":
                return {"message_thread_id": 55, "name": "Support", "icon_color": 7322096}
            if method == "editEphemeralMessageText":
                return {
                    "message_id": 0,
                    "date": 1700000001,
                    "chat": {"id": -100500, "type": "supergroup"},
                    "text": "Updated",
                }
            return True

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            topic = await adapter.create_forum_topic(777, "Support", icon_custom_emoji_id="5368324170671202286")
            self.assertEqual(topic["message_thread_id"], 55)
            await adapter.set_my_settings(has_topic_sidebar=True, callback_query_mode="inline")
            await adapter.edit_ephemeral_message(-100500, 888, "Updated")
            await adapter.delete_ephemeral_message(-100500, 888)
            await adapter.set_webhook("https://example.com/webhook", secret_token="sec123")
            await adapter.delete_webhook(drop_pending_updates=True)

        self.assertEqual(
            [m for m, _ in calls],
            [
                "createForumTopic",
                "setMySettings",
                "editEphemeralMessageText",
                "deleteEphemeralMessage",
                "setWebhook",
                "deleteWebhook",
            ],
        )
        self.assertEqual(
            calls[1][1],
            {"has_topic_sidebar": True, "callback_query_mode": "inline"},
        )

    async def test_zero_dep_webhook_server_end_to_end(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF", poll_timeout=1)
        sent: list[dict[str, object]] = []

        def fake_request(method: str, payload=None, **_kwargs):
            if method == "sendMessage":
                sent.append(dict(payload or {}))
                return {
                    "message_id": 12,
                    "date": 1700000002,
                    "chat": {"id": 900, "type": "private"},
                    "from": {"id": 999, "is_bot": True},
                    "text": (payload or {}).get("text", ""),
                }
            return True

        server = adapter.create_webhook_server(
            host="127.0.0.1",
            port=0,
            path="/tg-hook",
            secret_token="top-secret",
        )
        self.assertIsInstance(server, WebhookServer)
        await server.start()
        port = server.bound_port

        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("ping", prefix="/"))
        async def ping_cmd(ctx: Context) -> None:
            await ctx.reply("pong!")

        async def _consume_one() -> None:
            async for event in adapter.listen():
                await bot.dispatcher.dispatch(event, adapter)
                break

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            try:
                status_health, health_body = await _send_raw_http(port, "GET", "/health")
                self.assertEqual(status_health, 200)
                self.assertEqual(health_body, {"ok": True, "status": "healthy"})

                status_404, _ = await _send_raw_http(port, "POST", "/other", body=b"{}")
                self.assertEqual(status_404, 404)

                status_405, _ = await _send_raw_http(port, "GET", "/tg-hook")
                self.assertEqual(status_405, 405)

                status_403, _ = await _send_raw_http(
                    port,
                    "POST",
                    "/tg-hook",
                    body=b"{}",
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                )
                self.assertEqual(status_403, 403)

                consumer = asyncio.create_task(_consume_one())
                update_bytes = json.dumps(
                    {
                        "update_id": 99,
                        "message": {
                            "message_id": 11,
                            "date": 1700000000,
                            "chat": {"id": 900, "type": "private"},
                            "from": {"id": 900, "first_name": "Reza"},
                            "text": "/ping",
                        },
                    }
                ).encode("utf-8")
                status_200, ok_body = await _send_raw_http(
                    port,
                    "POST",
                    "/tg-hook",
                    body=update_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Telegram-Bot-Api-Secret-Token": "top-secret",
                    },
                )
                self.assertEqual(status_200, 200)
                self.assertEqual(ok_body, {"ok": True})
                await asyncio.wait_for(consumer, timeout=2.0)
            finally:
                await server.stop()

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["text"], "pong!")
