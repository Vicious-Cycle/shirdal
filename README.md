<div align="center">

# Shirdal

**A fast, context-first Python framework for Telegram Bot API and MTProto clients.**

**English** | [فارسی](README.fa.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

Shirdal separates your bot logic from the underlying transport. Write handlers, filters, FSM flows, and plugins once, then run them on the zero-dependency `BotAPIAdapter` (long polling or built-in `WebhookServer`), `TelethonAdapter`, `HydrogramAdapter`, or `MockAdapter` for offline tests.

## Highlights

- **Zero-Dependency Bot API (`BotAPIAdapter`):** Keep-Alive HTTP/HTTPS client with optional `msgspec` acceleration and a built-in `asyncio` `WebhookServer` (no FastAPI or aiohttp required).
- **Modern Bot API (9.4 – 10.5):** Colored buttons (`ButtonStyle`: `primary`, `success`, `danger`), custom/premium emoji icons (`icon`, `custom_emoji()`), `disabled` buttons, `date_time()`, group ephemeral replies (`ctx.reply_ephemeral()`), live AI draft streaming (`ctx.stream()`), `Rich Messages` (`ctx.reply_rich()`, `ctx.stream_rich()`), member tags (`ctx.set_member_tag()`), private chat topics, and `set_my_settings()`.
- **Pluggable MTProto (`TelethonAdapter` & `HydrogramAdapter`):** Clean `DeviceProfile` presets, `bot_token` and `StringSession` support, and automatic Pyrogram fallback.
- **Context-First Handlers & Filters:** `ctx.reply()`, `ctx.edit()`, `ctx.answer()`, `ctx.reply_media()`, `ctx.download()`, `ctx.react()`, `ctx.pin()`, moderation helpers, and composable filters (`command`, `regex`, `callback`, `state`, `private`, `group`, `incoming`, `outgoing`) using `&`, `|`, `~`.
- **Production Primitives:** Per-chat `AntiFloodAdapter` with `FloodWaitError` recovery, hot-reload `plugins/`, onion middlewares, `StatesGroup` FSM, `SQLiteStorage` (WAL + L1 cache), `RedisStorage`, `MySQLStorage`, `EncryptedStorage`, `MultiBot`, and `@bot.every()` scheduler.

## Installation

```bash
pip install shirdal

# Optional extras
pip install "shirdal[fast]"          # uvloop + msgspec
pip install "shirdal[telethon,fast]" # Telethon MTProto + speedups
```

## Quickstart (Bot API)

```python
import os
from shirdal import (
    BotAPIAdapter,
    Context,
    Shirdal,
    button,
    callback,
    command,
    custom_emoji,
    incoming,
    inline_keyboard,
)

adapter = BotAPIAdapter(os.environ["BOT_TOKEN"])
bot = Shirdal(adapter)

@bot.on(incoming & command("start", prefix="/"))
async def start(ctx: Context) -> None:
    badge = custom_emoji("5368324170671202286", "✨")
    kb = inline_keyboard([
        [
            button("Confirm", "act:ok", style="success", icon="5368324170671202286"),
            button("Cancel", "act:no", style="danger"),
        ]
    ])
    await ctx.reply(f"{badge} <b>Ready.</b> Choose an option:", reply_markup=kb)

@bot.on_callback(callback(prefix="act:"))
async def on_action(ctx: Context) -> None:
    await ctx.answer("Updated")
    await ctx.reply_ephemeral(f"Selected: <code>{ctx.callback_data}</code>")

if __name__ == "__main__":
    bot.run()
```

## Quickstart (MTProto Client)

```python
import os
from shirdal import Context, DeviceProfile, Shirdal, SQLiteStorage, TelethonAdapter, command, outgoing

adapter = TelethonAdapter(
    "my_account",
    int(os.environ["API_ID"]),
    os.environ["API_HASH"],
    device=DeviceProfile.desktop(),
)

bot = Shirdal(adapter, plugins_dir="plugins", hot_reload=True, storage=SQLiteStorage("shirdal.db"))

@bot.on(command("ping") & outgoing)
async def ping(ctx: Context) -> None:
    msg = await ctx.edit("Checking...")
    await msg.edit("Pong!", auto_delete=10)

if __name__ == "__main__":
    bot.run()
```

## Documentation

- [Getting Started & CLI](docs/getting-started.md)
- [Bot API Features (Colored Buttons, Emoji, Ephemeral, Streaming)](docs/bot-api.md)
- [Rich Messages Guide](docs/rich-messages.md)
- [Webhook Server & Production Deployment](docs/webhook-and-deployment.md)
- [مستندات فارسی](docs/fa/README.md)

## Running Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Contributing & License

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [LGPL-3.0-or-later](LICENSE).
