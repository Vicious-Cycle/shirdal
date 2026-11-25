from shirdal import AntiFloodAdapter, Context, SelfBot, command, outgoing


def setup(bot: SelfBot) -> None:
    @bot.on(command("ping") & outgoing)
    async def ping_cmd(ctx: Context) -> None:
        msg = await ctx.edit("⚡ Measuring...")
        await msg.edit("🏓 Pong! Shirdal v1.0.0", auto_delete=10)

    @bot.on(command("stats") & outgoing)
    async def stats_cmd(ctx: Context) -> None:
        if isinstance(bot.adapter, AntiFloodAdapter):
            s = bot.adapter.stats
            await ctx.edit(
                f"📊 Requests: {s.total_requests} | FloodWaits: {s.flood_waits_handled}",
                auto_delete=15,
            )
        else:
            await ctx.edit("📊 AntiFlood is disabled.", auto_delete=10)
