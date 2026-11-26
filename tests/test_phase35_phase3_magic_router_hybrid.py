import asyncio
import unittest

from shirdal import F, HybridAdapter, Router, Shirdal
from shirdal.core.events import ChatRef, EventType, MessageEvent, UpdateEvent, UserRef
from shirdal.core.mock_adapter import MockAdapter


class TestPhase3MagicRouterHybrid(unittest.TestCase):
    def test_magic_filter_expressions(self) -> None:
        async def run() -> None:
            adapter = MockAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
            matched: list[str] = []

            flt = F.text.startswith("https://") & F.text.contains("youtu") & (F.message.chat.type == "private")

            @bot.on(flt)
            async def on_yt(ctx) -> None:
                matched.append(ctx.text)

            m_ok = MessageEvent(
                id=1,
                chat=ChatRef(id=1, type="private"),
                sender=UserRef(id=2),
                text="https://youtube.com/watch?v=123",
            )
            m_group = MessageEvent(
                id=2,
                chat=ChatRef(id=3, type="group"),
                sender=UserRef(id=2),
                text="https://youtube.com/watch?v=123",
            )
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=m_ok), adapter)
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=m_group), adapter)
            await asyncio.sleep(0.03)
            self.assertEqual(matched, ["https://youtube.com/watch?v=123"])

        asyncio.run(run())

    def test_nested_router_and_scoped_middleware(self) -> None:
        async def run() -> None:
            adapter = MockAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
            log: list[str] = []

            parent = Router("parent")
            child = Router("child")

            @parent.use
            async def parent_mw(ctx, call_next):
                log.append("mw_before")
                await call_next(ctx)
                log.append("mw_after")

            @child.on(F.text == "go")
            async def child_handler(ctx) -> None:
                log.append("child_handler")

            parent.include_router(child)
            bot.include_router(parent)

            msg = MessageEvent(
                id=1, chat=ChatRef(id=1, type="private"), sender=UserRef(id=2), text="go"
            )
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=msg), adapter)
            await asyncio.sleep(0.03)
            self.assertEqual(log, ["mw_before", "child_handler", "mw_after"])

        asyncio.run(run())

    def test_hybrid_adapter_routes_large_media_to_mtproto(self) -> None:
        async def run() -> None:
            primary = MockAdapter()
            mtproto = MockAdapter()
            hybrid = HybridAdapter(primary, mtproto, large_file_threshold=100)

            await hybrid.connect()
            await hybrid.send_message(1, "hello")
            await hybrid.send_media(1, b"x" * 50, caption="small")
            await hybrid.send_media(1, b"y" * 150, caption="large")

            self.assertEqual(len(primary.sent_messages), 2)
            self.assertEqual(len(mtproto.sent_messages), 1)
            self.assertEqual(mtproto.sent_messages[0].text, "large")
            await hybrid.disconnect()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
