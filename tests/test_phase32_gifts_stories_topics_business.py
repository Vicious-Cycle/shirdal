import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

# Load botapi_adapter directly so tests run even if optional cryptography C-ext is unavailable.
_ADAPTER_PATH = Path(__file__).resolve().parents[1] / "src" / "shirdal" / "core" / "botapi_adapter.py"
_SPEC = importlib.util.spec_from_file_location("botapi_adapter_direct", _ADAPTER_PATH)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["botapi_adapter_direct"] = _MOD
_SPEC.loader.exec_module(_MOD)
BotAPIAdapter = _MOD.BotAPIAdapter


class TestBotAPIFeatures(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = BotAPIAdapter("123456:TEST_TOKEN")
        self.adapter._call = AsyncMock()

    def test_topics_methods(self) -> None:
        async def run() -> None:
            self.adapter._call.return_value = True
            self.assertTrue(
                await self.adapter.edit_forum_topic(-1001, 42, name="General", icon_custom_emoji_id="99")
            )
            self.adapter._call.assert_called_with(
                "editForumTopic",
                {"chat_id": -1001, "message_thread_id": 42, "name": "General", "icon_custom_emoji_id": "99"},
            )
            self.assertTrue(await self.adapter.close_forum_topic(-1001, 42))
            self.assertTrue(await self.adapter.reopen_forum_topic(-1001, 42))
            self.assertTrue(await self.adapter.delete_forum_topic(-1001, 42))
            self.assertTrue(await self.adapter.unpin_all_forum_topic_messages(-1001, 42))
            self.adapter._call.return_value = [{"custom_emoji_id": "1"}]
            stickers = await self.adapter.get_forum_topic_icon_stickers()
            self.assertEqual(stickers, [{"custom_emoji_id": "1"}])

        asyncio.run(run())

    def test_gifts_methods(self) -> None:
        async def run() -> None:
            self.adapter._call.return_value = {"gifts": [{"id": "g1", "star_count": 15}]}
            gifts = await self.adapter.get_available_gifts()
            self.assertEqual(gifts, [{"id": "g1", "star_count": 15}])

            self.adapter._call.return_value = True
            self.assertTrue(await self.adapter.send_gift("g1", user_id=777, text="Enjoy!"))
            self.adapter._call.assert_called_with(
                "sendGift",
                {"gift_id": "g1", "user_id": 777, "text": "Enjoy!"},
            )
            with self.assertRaises(ValueError):
                await self.adapter.send_gift("g1")

            self.assertTrue(await self.adapter.gift_premium_subscription(777, 3, 1000))

        asyncio.run(run())

    def test_stories_methods(self) -> None:
        async def run() -> None:
            self.adapter._call.return_value = {"id": 10, "chat": {"id": 1}}
            res = await self.adapter.post_story(
                "bc_1",
                {"type": "photo", "photo": "file_id"},
                86400,
                caption="Hello",
            )
            self.assertEqual(res["id"], 10)
            res_edit = await self.adapter.edit_story(
                "bc_1",
                10,
                {"type": "photo", "photo": "file_id_2"},
                caption="Updated",
            )
            self.assertEqual(res_edit["id"], 10)
            self.adapter._call.return_value = True
            self.assertTrue(await self.adapter.delete_story("bc_1", 10))

        asyncio.run(run())

    def test_business_methods(self) -> None:
        async def run() -> None:
            self.adapter._call.return_value = {"id": "bc_1", "is_enabled": True}
            conn = await self.adapter.get_business_connection("bc_1")
            self.assertTrue(conn["is_enabled"])

            self.adapter._call.return_value = True
            self.assertTrue(await self.adapter.read_business_message("bc_1", 100, 5))
            self.assertTrue(await self.adapter.delete_business_messages("bc_1", [5, 6]))
            self.assertTrue(await self.adapter.set_business_account_name("bc_1", "Shirdal", last_name="Bot"))
            self.assertTrue(await self.adapter.set_business_account_username("bc_1", username="shirdal_biz"))
            self.assertTrue(await self.adapter.set_business_account_bio("bc_1", bio="Telegram Framework"))
            self.assertTrue(
                await self.adapter.set_business_account_gift_settings(
                    "bc_1", True, {"unlimited_gifts": True}
                )
            )
            self.adapter._call.return_value = {"amount": 500}
            bal = await self.adapter.get_business_account_star_balance("bc_1")
            self.assertEqual(bal["amount"], 500)

            self.adapter._call.return_value = {"total_count": 1, "gifts": []}
            owned = await self.adapter.get_business_account_gifts("bc_1", limit=10)
            self.assertEqual(owned["total_count"], 1)

            self.adapter._call.return_value = True
            self.assertTrue(await self.adapter.convert_gift_to_stars("bc_1", "og_1"))
            self.assertTrue(await self.adapter.upgrade_gift("bc_1", "og_1", star_count=25))
            self.assertTrue(await self.adapter.transfer_gift("bc_1", "og_1", 999))

        asyncio.run(run())

    def test_set_my_settings(self) -> None:
        async def run() -> None:
            self.adapter._call.return_value = True
            self.assertTrue(
                await self.adapter.set_my_settings(
                    can_join_groups=True,
                    can_read_all_group_messages=False,
                    is_inline=True,
                    inline_query_placeholder="Search...",
                    needs_inline_query_location=False,
                    has_topics_enabled=True,
                    has_topic_sidebar=True,
                    callback_query_mode="inline",
                )
            )
            self.adapter._call.assert_called_with(
                "setMySettings",
                {
                    "can_join_groups": True,
                    "can_read_all_group_messages": False,
                    "is_inline": True,
                    "needs_inline_query_location": False,
                    "has_topics_enabled": True,
                    "has_topic_sidebar": True,
                    "inline_query_placeholder": "Search...",
                    "callback_query_mode": "inline",
                },
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
