from shirdal import Context, SelfBot, State, StatesGroup, command, outgoing, state


class NoteWizard(StatesGroup):
    waiting_body = State()


def setup(bot: SelfBot) -> None:
    @bot.on(state(None) & command("note") & outgoing)
    async def start_note(ctx: Context) -> None:
        await ctx.state.set(NoteWizard.waiting_body)
        await ctx.reply("✍️ Send the note text:")

    @bot.on(state(NoteWizard.waiting_body) & outgoing)
    async def save_note(ctx: Context) -> None:
        await ctx.reply(f"📝 Saved note: {ctx.text}", auto_delete=10)
        await ctx.state.clear()
