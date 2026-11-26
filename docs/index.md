# Shirdal

[![PyPI](https://img.shields.io/pypi/v/shirdal.svg?color=007ec6)](https://pypi.org/project/shirdal/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%2B-3776AB.svg)](https://www.python.org/downloads/)
[![shircrypt](https://img.shields.io/badge/crypto-shircrypt%20Rust-d4a843.svg)](https://github.com/Vicious-Cycle/shircrypt)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](https://github.com/Vicious-Cycle/shirdal/blob/main/LICENSE)

**Shirdal** is a modern, context-first asynchronous Python framework for Telegram — uniting **Bot API 10.5** and a **Native MTProto 2.0** client (accelerated by Rust [`shircrypt`](https://github.com/Vicious-Cycle/shircrypt)) behind one clean `TransportAdapter` interface.

**Documentation:** [English](getting-started.md) · [فارسی](fa/README.md) · [Download Full Docs (.md)](shirdal-docs.md){ download="shirdal-docs.md" }

## Features

- **Unified Bot API & MTProto 2.0**: Write handlers once and run them on `BotAPIAdapter`, `NativeMTProtoAdapter`, `TelethonAdapter`, `HydrogramAdapter`, or `HybridAdapter`.
- **Rust-Accelerated Crypto (`shircrypt`)**: Up to **11.84x faster** (4.67x geometric mean) than `TgCrypto`, with GIL release on large buffers and native MTProto 2.0 KDF.
- **Modular Routers & Magic Filter `F`**: Organize large bots with nestable `Router`s and zero-dependency `F.text.startswith(...)` expressions.
- **Full FSM + `await ctx.ask()`**: Declarative `StatesGroup`, `FSMStrategy`, TTL-enabled `MemoryStorage` / `RedisStorage` / `SQLiteStorage`, plus one-line `ctx.ask()` conversations.
- **Production Ready**: Built-in `AntiFloodAdapter`, `WebhookServer`, `Hot-Reload` plugins, `MultiBot`, and `MockAdapter` for offline testing.

!!! tip "Startup Diagnostics"
    On startup, Shirdal measures connection latency and prints active extensions:
    ```text
    Bot is running...
    shirdal 1.0.14
    adapter: BotAPIAdapter
    loop:    uvloop
    json:    msgspec
    crypto:  shircrypt-rust (v1.0.6)
    bot:     @MyBot

    ping:    38.4ms
    ```

## Simple Usage

```python
import os
from shirdal import BotAPIAdapter, Context, F, Router, Shirdal

router = Router("main")

@router.on_command("start")
async def start(ctx: Context) -> None:
    name_ctx = await ctx.ask("What is your name?", timeout=60, filters=F.text)
    await name_ctx.reply(f"Hello <b>{name_ctx.text}</b>!")

if __name__ == "__main__":
    bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))
    bot.include_router(router)
    bot.run()
```

## Full Documentation Index

### Getting Started & Core
- [Getting Started & CLI](getting-started.md)
- [Bot API 10.5 Features](bot-api.md)
- [Rich Messages & Streaming](rich-messages.md)
- [Native MTProto 2.0 Core](native-mtproto.md)
- [Hybrid Mode (Bot API + 50MB+ MTProto Uploads)](hybrid-mode.md)

### Routing, Filters & FSM
- [Routers & Magic Filter `F`](routing-and-filters.md)
- [FSM, Persistent Storage (TTL) & `await ctx.ask()`](fsm-and-storage.md)

### Production, Tooling & Migration
- [Middlewares, Anti-Flood & Error Handling](middleware-and-antiflood.md)
- [Plugins, Hot-Reload & Scheduler](plugins-and-scheduler.md)
- [MultiBot & Encrypted Storage](multibot-and-storage.md)
- [Offline Testing (`MockAdapter`) & CLI](testing-and-cli.md)
- [Webhook & Deployment](webhook-and-deployment.md)
- [Migrating from aiogram / Pyrogram](migration.md)
- [Changelog](changelog.md)

### API Reference
- [Client, Router & MultiBot API](api/client.md)
- [Context & FSM API](api/context-fsm.md)
- [Adapters API (`BotAPIAdapter`, `NativeMTProtoAdapter`, `HybridAdapter`, `MockAdapter`)](api/adapters.md)
- [Filters, Guard & Storage API](api/guard-storage.md)

### فارسی
- [مستندات کامل فارسی (Shirdal)](fa/README.md)
