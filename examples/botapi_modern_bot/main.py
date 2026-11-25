"""Modern Bot API example using colored buttons, custom emoji, ephemeral replies, and Rich Messages."""

import os

from shirdal import (
    BotAPIAdapter,
    ButtonStyle,
    Context,
    Shirdal,
    button,
    callback,
    command,
    custom_emoji,
    date_time,
    incoming,
    inline_keyboard,
    rich_buttons,
    rich_heading,
    rich_table,
)

adapter = BotAPIAdapter(os.environ["BOT_TOKEN"])
bot = Shirdal(adapter)


@bot.on(incoming & command("start", prefix="/"))
async def start_cmd(ctx: Context) -> None:
    icon = custom_emoji("5368324170671202286", "✨")
    kb = inline_keyboard(
        [
            [
                button("Confirm", "act:confirm", style=ButtonStyle.SUCCESS, icon="5368324170671202286"),
                button("Delete", "act:delete", style=ButtonStyle.DANGER),
            ],
            [button("Locked", "act:locked", style="primary", disabled=True)],
        ]
    )
    await ctx.reply(f"{icon} <b>Control Panel</b>", reply_markup=kb)


@bot.on_callback(callback(prefix="act:"))
async def on_action(ctx: Context) -> None:
    await ctx.answer("Done")
    await ctx.reply_ephemeral(f"Action triggered: <code>{ctx.callback_data}</code>")


@bot.on(incoming & command("report", prefix="/"))
async def report_cmd(ctx: Context) -> None:
    async with ctx.stream_rich(can_stop=True) as stream:
        await stream.thinking("Preparing summary...")
        await stream.update(
            blocks=[
                rich_heading("Daily Summary", size=1),
                rich_table(
                    [["Active Users", "1,420"], ["Uptime", "99.98%"]],
                    headers=["Metric", "Value"],
                    caption=date_time(1764100000, "Today"),
                ),
                rich_buttons([button("Refresh", "act:refresh", style="primary")], align="center"),
            ]
        )


if __name__ == "__main__":
    bot.run()
