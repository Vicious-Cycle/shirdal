import asyncio
import unittest

from shirdal import (
    Context,
    MockAdapter,
    SelfBot,
    command,
    incoming,
    outgoing,
    private,
    regex,
)


class TestPhase2Engine(unittest.IsolatedAsyncioTestCase):
    async def test_command_args_and_edit_auto_delete(self) -> None:
        adapter = MockAdapter()
        bot = SelfBot(adapter, use_uvloop=False)
        captured_args: list[str] = []

        @bot.on(command("echo", prefix=(".", "/")) & outgoing)
        async def echo_handler(ctx: Context) -> None:
            captured_args.extend(ctx.args)
            edited = await ctx.edit(f"Echo: {ctx.arg_str}", auto_delete=0.03)
            self.assertEqual(edited.text, "Echo: hello world")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)

        # Should match: outgoing + prefix "."
        await adapter.push_incoming(".echo hello world", chat_id=99, is_outgoing=True)
        # Should NOT match: incoming message
        await adapter.push_incoming(".echo ignored", chat_id=99, is_outgoing=False)

        await asyncio.sleep(0.08)
        await bot.stop()
        await serve_task

        self.assertEqual(captured_args, ["hello", "world"])
        self.assertEqual(len(adapter.edited_messages), 1)
        self.assertEqual(len(adapter.deleted_ids), 1)
        self.assertEqual(adapter.deleted_ids[0][0], 99)

    async def test_composable_or_not_and_regex_filters(self) -> None:
        adapter = MockAdapter()
        bot = SelfBot(adapter, use_uvloop=False)
        matches: list[str] = []

        @bot.on((incoming | ~private) & regex(r"code=(\d+)"))
        async def code_handler(ctx: Context) -> None:
            assert ctx.match is not None
            matches.append(ctx.match.group(1))
            await ctx.reply(f"Got {ctx.match.group(1)}")

        serve_task = asyncio.create_task(bot.serve())
        await asyncio.sleep(0.02)

        await adapter.push_incoming("here is code=742", chat_id=7, is_outgoing=False)
        await asyncio.sleep(0.05)

        await bot.stop()
        await serve_task

        self.assertEqual(matches, ["742"])
        self.assertEqual(adapter.sent_messages[0].text, "Got 742")
