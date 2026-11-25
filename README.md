<div align="center">

# Shirdal

**A fast, clean, context-first Python self-bot framework for Telegram.**

**English** | [فارسی](README.fa.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

## Features

- **Pluggable MTProto Core (`TransportAdapter`):** Decoupled from the underlying client, shipping with `TelethonAdapter`, `HydrogramAdapter`, `DeviceProfile` presets, `StringSession` support, and an in-memory `MockAdapter` for offline testing.
- **Context-First API (`ctx`):** Ergonomic `ctx.reply()`, `ctx.edit()`, `ctx.reply_media()`, `ctx.reply_album()`, `ctx.download()`, `ctx.react()`, `ctx.pin()`, `ctx.ban()`, `ctx.mute()`, `ctx.kick()`, `ctx.get_chat()`, non-blocking `auto_delete`, and `async with ctx.typing():`.
- **Composable Filters:** Combine `command`, `regex`, `state`, `outgoing`, `incoming`, `private`, `group`, `reply`, and `text` using `&`, `|`, and `~`.
- **Smart Anti-Flood Guard:** Per-chat pacing, concurrency limits, global cooldown propagation, and automatic `FloodWaitError` recovery.
- **Live Hot-Reload Plugins:** Drop `.py` modules with `setup(bot)` / `teardown(bot)` into `plugins/` and reload on save without dropping the Telegram connection.
- **Middleware & FSM:** Onion-style `@bot.use` middlewares, global `@bot.on_error` handlers, and `StatesGroup` multi-step flows.
- **Storage & Encryption:** Tuned WAL-mode `SQLiteStorage` (with L1 RAM cache), `RedisStorage`, `MySQLStorage`, and `EncryptedStorage` (`Encrypt-then-MAC`).
- **MultiBot & Scheduler:** Run multiple accounts concurrently under `MultiBot` and schedule periodic tasks with `@bot.every(...)`.
- **Uploader Optimizations:** Throttled `ProgressTracker` and bounded `TransferQueue`.
- **Developer CLI:** `shirdal new`, `shirdal doctor`, and `shirdal run`.

## Installation

```bash
pip install shirdal
# With Telethon + uvloop:
pip install "shirdal[telethon,fast]"
```

## Quickstart

```python
import os
from shirdal import Context, DeviceProfile, SelfBot, SQLiteStorage, TelethonAdapter, command, outgoing

adapter = TelethonAdapter(
    "my_account",
    int(os.environ["API_ID"]),
    os.environ["API_HASH"],
    device=DeviceProfile.desktop(),
)

bot = SelfBot(
    adapter,
    anti_flood=True,
    plugins_dir="plugins",
    hot_reload=True,
    storage=SQLiteStorage("shirdal.db"),
)

@bot.on(command("ping") & outgoing)
async def ping(ctx: Context) -> None:
    msg = await ctx.edit("Checking...")
    await msg.edit("Pong!", auto_delete=10)

if __name__ == "__main__":
    bot.run()
```

## Running Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## License

Licensed under the [LGPL-3.0-or-later](LICENSE).
