import asyncio
import unittest

from shirdal import AntiFloodConfig, Context, MockAdapter, MultiBot, command, outgoing


class TestPhase7MultiBot(unittest.IsolatedAsyncioTestCase):
    async def test_multibot_shared_handlers_and_independent_lifecycle(self) -> None:
        fleet = MultiBot(use_uvloop=False)
        raw1 = MockAdapter()
        raw2 = MockAdapter()

        bot1 = fleet.add_adapter(
            "acc1",
            raw1,
            anti_flood=True,
            flood_config=AntiFloodConfig(per_chat_interval=0.02),
        )
        fleet.add_adapter("acc2", raw2, anti_flood=False)

        @fleet.on(command("whoami") & outgoing)
        async def whoami(ctx: Context) -> None:
            await ctx.reply(f"chat:{ctx.chat_id}")

        @bot1.on(command("only1"))
        async def only_acc1(ctx: Context) -> None:
            await ctx.reply("acc1-exclusive")

        fleet_task = asyncio.create_task(fleet.serve_all())
        await asyncio.sleep(0.03)

        status = fleet.status()
        self.assertTrue(status["acc1"]["connected"])
        self.assertTrue(status["acc2"]["connected"])

        await raw1.push_incoming(".whoami", chat_id=101, is_outgoing=True)
        await raw2.push_incoming(".whoami", chat_id=202, is_outgoing=True)
        await raw1.push_incoming(".only1", chat_id=101, is_outgoing=True)
        await raw2.push_incoming(".only1", chat_id=202, is_outgoing=True)
        await asyncio.sleep(0.08)

        self.assertEqual([m.text for m in raw1.sent_messages], ["chat:101", "acc1-exclusive"])
        self.assertEqual([m.text for m in raw2.sent_messages], ["chat:202"])

        # Stop acc1 individually while acc2 stays connected
        await fleet.stop_account("acc1")
        self.assertFalse(raw1.is_connected)
        self.assertTrue(raw2.is_connected)

        await fleet.stop_all()
        await fleet_task
        self.assertFalse(raw2.is_connected)
