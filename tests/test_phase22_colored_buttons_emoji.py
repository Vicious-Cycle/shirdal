import asyncio
import unittest
from unittest.mock import patch

from shirdal import (
    BotAPIAdapter,
    ButtonStyle,
    Context,
    Shirdal,
    button,
    command,
    custom_emoji,
    custom_emoji_entity,
    incoming,
    inline_keyboard,
    reply_button,
    reply_keyboard,
)


class TestPhase22ColoredButtonsAndPremiumEmoji(unittest.IsolatedAsyncioTestCase):
    def test_colored_inline_buttons_and_icons(self) -> None:
        kb = inline_keyboard(
            [
                [
                    button("Confirm", "act:ok", style="success", icon="5368324170671202286"),
                    button("Delete", "act:del", style=ButtonStyle.DANGER),
                ],
                [
                    button("Primary", "act:main", style="PRIMARY", disabled=True),
                    button("Copy", copy_text="SHIRDAL-102"),
                ],
            ],
            force_reply=True,
        )

        self.assertEqual(
            kb,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Confirm",
                            "callback_data": "act:ok",
                            "style": "success",
                            "icon_custom_emoji_id": "5368324170671202286",
                        },
                        {
                            "text": "Delete",
                            "callback_data": "act:del",
                            "style": "danger",
                        },
                    ],
                    [
                        {
                            "text": "Primary",
                            "callback_data": "act:main",
                            "style": "primary",
                            "disabled": True,
                        },
                        {
                            "text": "Copy",
                            "copy_text": {"text": "SHIRDAL-102"},
                        },
                    ],
                ],
                "force_reply": True,
            },
        )

    def test_invalid_button_style_raises(self) -> None:
        with self.assertRaises(ValueError):
            button("Bad", "cb:bad", style="neon")
        with self.assertRaises(ValueError):
            reply_button("Bad", style="warning")

    def test_reply_keyboard_with_colored_buttons_and_icons(self) -> None:
        rkb = reply_keyboard(
            [
                [
                    reply_button("Pay", style="primary", icon_custom_emoji_id="51234567890"),
                    "Help",
                ],
                [
                    reply_button("Share Contact", style="success", request_contact=True),
                ],
            ],
            one_time_keyboard=True,
            input_field_placeholder="Choose an option",
        )
        self.assertEqual(
            rkb,
            {
                "keyboard": [
                    [
                        {
                            "text": "Pay",
                            "style": "primary",
                            "icon_custom_emoji_id": "51234567890",
                        },
                        {"text": "Help"},
                    ],
                    [
                        {
                            "text": "Share Contact",
                            "style": "success",
                            "request_contact": True,
                        }
                    ],
                ],
                "resize_keyboard": True,
                "one_time_keyboard": True,
                "input_field_placeholder": "Choose an option",
            },
        )

    def test_custom_emoji_helpers(self) -> None:
        tag = custom_emoji("5368324170671202286", fallback="🔥")
        self.assertEqual(tag, '<tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji>')

        escaped = custom_emoji('123"45', fallback="<ok>")
        self.assertEqual(escaped, '<tg-emoji emoji-id="123&quot;45">&lt;ok&gt;</tg-emoji>')

        ent = custom_emoji_entity(0, 2, "5368324170671202286")
        self.assertEqual(
            ent,
            {
                "type": "custom_emoji",
                "offset": 0,
                "length": 2,
                "custom_emoji_id": "5368324170671202286",
            },
        )

        with self.assertRaises(ValueError):
            custom_emoji("")

    async def test_end_to_end_send_colored_buttons_and_premium_emoji(self) -> None:
        adapter = BotAPIAdapter("123456:ABC-DEF", poll_timeout=1)
        sent_payloads: list[dict[str, object]] = []
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
                                "message_id": 42,
                                "date": 1700000000,
                                "chat": {"id": 777, "type": "private"},
                                "from": {"id": 777, "first_name": "Sara"},
                                "text": "/menu",
                            },
                        }
                    ]
                return []
            if method == "sendMessage":
                sent_payloads.append(dict(payload or {}))
                return {
                    "message_id": 43,
                    "date": 1700000001,
                    "chat": {"id": 777, "type": "private"},
                    "from": {"id": 999, "is_bot": True},
                    "text": (payload or {}).get("text", ""),
                }
            return True

        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)

        @bot.on(incoming & command("menu", prefix="/"))
        async def menu_cmd(ctx: Context) -> None:
            fire = custom_emoji("5368324170671202286", "🔥")
            kb = inline_keyboard(
                [
                    [
                        button("Approve", "ok", style="success", icon="5368324170671202286"),
                        button("Reject", "no", style="danger"),
                    ]
                ]
            )
            await ctx.reply(f"{fire} <b>Choose an action</b>", reply_markup=kb)

        with patch.object(adapter, "_request_sync", side_effect=fake_request):
            serve_task = asyncio.create_task(bot.serve())
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task

        self.assertEqual(len(sent_payloads), 1)
        payload = sent_payloads[0]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn('<tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji>', str(payload["text"]))
        markup = payload["reply_markup"]
        self.assertEqual(markup["inline_keyboard"][0][0]["style"], "success")
        self.assertEqual(markup["inline_keyboard"][0][0]["icon_custom_emoji_id"], "5368324170671202286")
        self.assertEqual(markup["inline_keyboard"][0][1]["style"], "danger")
