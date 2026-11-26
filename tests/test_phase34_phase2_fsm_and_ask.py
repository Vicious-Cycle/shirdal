import asyncio
import unittest

from shirdal import Shirdal, command, state, text
from shirdal.core.events import ChatRef, EventType, MessageEvent, UpdateEvent, UserRef
from shirdal.core.mock_adapter import MockAdapter
from shirdal.engine.fsm import ANY_STATE, FSMStrategy, MemoryStorage, State, StatesGroup
from shirdal.storage.redis import RedisStorage


class _Form(StatesGroup):
    step1 = State()
    step2 = State()


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, val: str, ex: int | None = None) -> None:
        self.store[key] = val
        self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)


class TestPhase2FSMAndAsk(unittest.TestCase):
    def test_memory_storage_ttl_expiration(self) -> None:
        async def run() -> None:
            st = MemoryStorage(ttl=0.05)
            await st.set_state((1, 2), "Form:step1")
            await st.update_data((1, 2), name="ali")
            self.assertEqual(await st.get_state((1, 2)), "Form:step1")
            await asyncio.sleep(0.07)
            self.assertIsNone(await st.get_state((1, 2)))
            self.assertEqual(await st.get_data((1, 2)), {})

        asyncio.run(run())

    def test_redis_storage_fsm_ttl(self) -> None:
        async def run() -> None:
            fake = _FakeAsyncRedis()
            rs = RedisStorage(client=fake, fsm_ttl=1800)
            await rs.set_state((10, 20), "Form:step1")
            self.assertEqual(fake.ttls["shirdal:fsm:10:20"], 1800)
            self.assertEqual(await rs.get_state((10, 20)), "Form:step1")

        asyncio.run(run())

    def test_multistate_and_any_state_filter(self) -> None:
        async def run() -> None:
            adapter = MockAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
            hits: list[str] = []

            @bot.on(state(_Form.step1, _Form.step2))
            async def h_multi(ctx) -> None:
                hits.append("multi")

            @bot.on(state(ANY_STATE))
            async def h_any(ctx) -> None:
                hits.append("any")

            msg = MessageEvent(
                id=1, chat=ChatRef(id=1, type="private"), sender=UserRef(id=2), text="hi"
            )
            # No state yet -> neither should fire
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=msg), adapter)
            await asyncio.sleep(0.03)
            self.assertEqual(hits, [])

            await bot.dispatcher.storage.set_state((1, 2), _Form.step2.name)
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=msg), adapter)
            await asyncio.sleep(0.03)
            self.assertEqual(hits, ["multi", "any"])

        asyncio.run(run())

    def test_ctx_ask_conversation_flow_and_timeout(self) -> None:
        async def run() -> None:
            adapter = MockAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
            answers: list[str] = []
            fallback_hits: list[str] = []

            @bot.on(command("reg", prefix="/"))
            async def reg(ctx) -> None:
                reply_ctx = await ctx.ask("Your name?", timeout=1.0, filters=text)
                answers.append(reply_ctx.text)
                await reply_ctx.reply(f"Hi {reply_ctx.text}")

            @bot.on(text)
            async def catch_all(ctx) -> None:
                fallback_hits.append(ctx.text)

            m1 = MessageEvent(
                id=1, chat=ChatRef(id=100, type="private"), sender=UserRef(id=200), text="/reg"
            )
            m2 = MessageEvent(
                id=2, chat=ChatRef(id=100, type="private"), sender=UserRef(id=200), text="Reza"
            )
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=m1), adapter)
            await asyncio.sleep(0.02)
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=m2), adapter)
            await asyncio.sleep(0.03)

            self.assertEqual(answers, ["Reza"])
            # /reg matched catch_all once, but "Reza" was consumed by ask() waiter
            self.assertEqual(fallback_hits, ["/reg"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
