# Hybrid Mode (Bot API + 50MB+ MTProto Uploads)

Telegram's Bot API caps file uploads at **50 MiB**, while MTProto supports up to **2 GiB** (or 4 GiB with Premium). `HybridAdapter` gives you the best of both worlds:

- Messages, inline buttons, callbacks, webhooks, and files `<= 50 MiB` go through **BotAPIAdapter**.
- Any file `> 50 MiB` passed to `ctx.reply_media(...)` automatically routes through **NativeMTProtoAdapter** accelerated by **`shircrypt`** (4.67x faster on average than `TgCrypto`, GIL-free on large buffers).

```python
import os
from shirdal import (
    BotAPIAdapter, DeviceProfile, HybridAdapter,
    NativeMTProtoAdapter, Shirdal, command,
)

bot_api = BotAPIAdapter(os.environ["BOT_TOKEN"])
mtproto = NativeMTProtoAdapter(
    int(os.environ["API_ID"]),
    os.environ["API_HASH"],
    session_path="uploader.sqlite",
    device=DeviceProfile.desktop(),
)

bot = Shirdal(HybridAdapter(bot_api, mtproto))

@bot.on(command("dl", prefix="/"))
async def send_video(ctx):
    # Automatically uses Bot API for <=50 MiB and MTProto+shircrypt for >50 MiB
    await ctx.reply_media("video.mp4", caption="Done!")
```
