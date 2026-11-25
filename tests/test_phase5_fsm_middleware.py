import asyncio
import unittest

from shirdal import (
    Context,
    MockAdapter,
    NextHandler,
    SelfBot,
    State,
    StatesGroup,
    command,
    outgoing,
    state,
)


class ProfileStates(StatesGroup):
    waiting_name = State()
    waiting_age = State()


class TestPhase5FSMMiddleware(unittest.IsolatedAsyncioTestCase):
    async def test_middleware_onion_order_and_short_circuit(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)
        trace: list[str] = []

        @bot.use
        async def mw_guard(ctx: Context, call_next: NextHandler) -> None:
            trace.append("mw1:in")
            if ctx.text == "blocked":
                trace.append("mw1:blocked")
                return
            await call_next(ctx)
            trace.append("mw1:out")

        @bot.use
        async def mw_logger(ctx: Context, call_next: NextHandler) -> None:
            trace.append("mw2:in")
            await call_next(ctx)
            trace.append("mw2:out")

        @bot.on_message
        async def handle(ctx: Context) -> None:
            trace.append("handler")
            await ctx.reply("ok")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)

        await raw.push_incoming("blocked", chat_id=1)
        await asyncio.sleep(0.03)
        self.assertEqual(trace, ["mw1:in", "mw1:blocked"])
        self.assertEqual(len(raw.sent_messages), 0)

        trace.clear()
        await raw.push_incoming("hello", chat_id=1)
        await asyncio.sleep(0.03)
        self.assertEqual(
            trace, ["mw1:in", "mw2:in", "handler", "mw2:out", "mw1:out"]
        )
        self.assertEqual(raw.sent_messages[0].text, "ok")

        await bot.stop()
        await serve_task

    async def test_fsm_multistep_conversation_flow(self) -> None:
        raw = MockAdapter()
        bot = SelfBot(raw, use_uvloop=False, anti_flood=False)

        @bot.on(state(None) & command("reg") & outgoing)
        async def start_reg(ctx: Context) -> None:
            await ctx.state.set(ProfileStates.waiting_name)
            await ctx.reply("Name?")

        @bot.on(state(ProfileStates.waiting_name) & outgoing)
        async def got_name(ctx: Context) -> None:
            await ctx.state.update(name=ctx.text)
            await ctx.state.set(ProfileStates.waiting_age)
            await ctx.reply("Age?")

        @bot.on(state(ProfileStates.waiting_age) & outgoing)
        async def got_age(ctx: Context) -> None:
            data = await ctx.state.data()
            await ctx.reply(f"Saved {data['name']} ({ctx.text})")
            await ctx.state.clear()

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)

        await raw.push_incoming(".reg", chat_id=5, sender_id=10, is_outgoing=True)
        await asyncio.sleep(0.03)
        await raw.push_incoming("Ali", chat_id=5, sender_id=10, is_outgoing=True)
        await asyncio.sleep(0.03)
        await raw.push_incoming("25", chat_id=5, sender_id=10, is_outgoing=True)
        await asyncio.sleep(0.03)

        self.assertEqual(
            [m.text for m in raw.sent_messages],
            ["Name?", "Age?", "Saved Ali (25)"],
        )

        # State should now be cleared
        current = await bot.dispatcher.storage.get_state((5, 10))
        self.assertIsNone(current)

        await bot.stop()
        await serve_task
