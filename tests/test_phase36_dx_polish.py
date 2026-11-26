import asyncio
import importlib
import sys
import unittest

import shirdal
from shirdal import ChatRef, Context, F, MessageEvent, MockAdapter, Router, Shirdal, UpdateEvent, UserRef
from shirdal.core.events import EventType


def _make_msg(text: str, *, is_outgoing: bool = False, msg_id: int = 1) -> UpdateEvent:
    return UpdateEvent(
        type=EventType.NEW_MESSAGE,
        message=MessageEvent(
            id=msg_id,
            chat=ChatRef(id=100, type="private"),
            sender=UserRef(id=200, username="tester", first_name="Test"),
            text=text,
            is_outgoing=is_outgoing,
        ),
    )


class TestPhase36DXPolish(unittest.IsolatedAsyncioTestCase):
    def test_lazy_exports_and_rich_submodule(self) -> None:
        self.assertIn("NativeMTProtoAdapter", dir(shirdal))
        for name in shirdal.__all__:
            self.assertIsNotNone(getattr(shirdal, name))

        from shirdal import rich

        self.assertTrue(set(rich.__all__).issubset(set(shirdal.__all__)))
        self.assertEqual(rich.button("OK", "ok")["text"], "OK")

    def test_lazy_import_defers_heavy_modules(self) -> None:
        for mod in list(sys.modules):
            if mod == "shirdal" or mod.startswith("shirdal."):
                sys.modules.pop(mod, None)

        pkg = importlib.import_module("shirdal")
        self.assertNotIn("shirdal.core.native_mtproto_adapter", sys.modules)
        self.assertNotIn("shirdal.storage.redis", sys.modules)
        _ = pkg.Shirdal
        self.assertNotIn("shirdal.storage.redis", sys.modules)
        self.assertNotIn("shirdal.storage.mysql", sys.modules)

    async def test_client_on_command_and_on_message_variants(self) -> None:
        adapter = MockAdapter()
        bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
        seen: list[str] = []

        @bot.on_command("start")
        async def start_cmd(ctx: Context) -> None:
            seen.append(f"cmd:{ctx.command}:{ctx.arg_str}")

        @bot.on_message(F.text == "ping")
        async def filtered_msg(ctx: Context) -> None:
            seen.append("filtered:ping")

        @bot.on_message
        async def catch_all(ctx: Context) -> None:
            seen.append(f"all:{ctx.text}")

        await bot._dispatch_update(_make_msg("/start hello"))
        await bot._dispatch_update(_make_msg("ping"))
        await bot._dispatch_update(_make_msg("other"))
        # Outgoing /start should be ignored by default only_incoming=True
        await bot._dispatch_update(_make_msg("/start out", is_outgoing=True))
        await asyncio.sleep(0.05)

        self.assertEqual(
            seen,
            [
                "cmd:start:hello",
                "all:/start hello",
                "filtered:ping",
                "all:ping",
                "all:other",
                "all:/start out",
            ],
        )

    async def test_router_on_command_and_on_message_variants(self) -> None:
        adapter = MockAdapter()
        bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
        router = Router("dx")
        seen: list[str] = []

        @router.on_command(["help", "h"], prefix=".", only_incoming=False)
        async def help_cmd(ctx: Context) -> None:
            seen.append(f"router_cmd:{ctx.command}")

        @router.on_message(F.text.startswith("hi"))
        async def hi_msg(ctx: Context) -> None:
            seen.append(f"router_hi:{ctx.text}")

        @router.on_message
        async def fallback_msg(ctx: Context) -> None:
            seen.append(f"router_all:{ctx.text}")

        bot.include_router(router)

        await bot._dispatch_update(_make_msg(".help", is_outgoing=True))
        await bot._dispatch_update(_make_msg("hi there"))
        await bot._dispatch_update(_make_msg("bye"))
        await asyncio.sleep(0.05)

        self.assertEqual(
            seen,
            [
                "router_cmd:help",
                "router_all:.help",
                "router_hi:hi there",
                "router_all:hi there",
                "router_all:bye",
            ],
        )
