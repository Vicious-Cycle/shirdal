# Shirdal

![Shirdal Logo](assets/logo-banner.png){ width="460" }

**One Python framework for Telegram bots and userbots.**
Write your handlers once, run them on the Bot API, on a native MTProto 2.0 client, or combine both with `HybridAdapter` (accelerated by [`shircrypt`](https://github.com/Vicious-Cycle/shircrypt)).

## Installation

```bash
pip install shirdal
pip install "shirdal[fast]"       # uvloop + msgspec + shircrypt (~4.7x faster crypto)
pip install "shirdal[shircrypt]"  # Rust-accelerated AES-IGE / CTR / KDF
```

## Quick Start

```python
import os
from shirdal import BotAPIAdapter, Context, F, Shirdal, command, incoming

bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))

@bot.on(incoming & command("start", prefix="/"))
async def start(ctx: Context) -> None:
    name_ctx = await ctx.ask("What is your name?", timeout=60, filters=F.text)
    await name_ctx.reply(f"Hello <b>{name_ctx.text}</b>!")

if __name__ == "__main__":
    bot.run()
```
