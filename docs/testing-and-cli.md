# Offline Testing (`MockAdapter`) & CLI

## Testing Without Telegram

```python
import asyncio
from shirdal import MockAdapter, Shirdal, command
from shirdal.core.events import ChatRef, EventType, MessageEvent, UpdateEvent, UserRef

async def test_bot():
    adapter = MockAdapter()
    bot = Shirdal(adapter, anti_flood=False, startup_banner=False)

    @bot.on(command("hi", prefix="/"))
    async def hi(ctx):
        await ctx.reply("Hello!")

    msg = MessageEvent(id=1, chat=ChatRef(id=1, type="private"), sender=UserRef(id=2), text="/hi")
    await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=msg), adapter)
    await asyncio.sleep(0.02)
    assert adapter.sent_messages[0].text == "Hello!"
```

## CLI Commands

```bash
shirdal new my_bot --adapter botapi   # Scaffold a new project
shirdal doctor                        # Inspect Python, uvloop, msgspec, shircrypt
shirdal run main.py                   # Run an entry script
```
