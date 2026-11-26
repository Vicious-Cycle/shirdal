# Shirdal Complete Documentation

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
    shirdal 1.0.13
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


---

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


---

# Routers & Magic Filter `F`

## Modular Routers

Split your bot into clean modules using `Router`, then attach them to `Shirdal` (or nest routers inside each other):

```python
from shirdal import F, Router, command

admin_router = Router("admin")

@admin_router.use
async def admin_only(ctx, call_next):
    if ctx.sender_id != 123456789:
        return
    await call_next(ctx)

@admin_router.on_command("stats")
async def stats(ctx):
    await ctx.reply("All systems operational.")

# In main.py:
# bot.include_router(admin_router)
```

## Magic Filter `F`

`F` lets you write concise, zero-dependency inline filters that compose seamlessly with `&`, `|`, and `~`:

```python
from shirdal import F

yt_private = F.text.startswith("https://") & F.text.contains("youtu") & (F.message.chat.type == "private")
ok_btn = F.callback_data.startswith("act:")
vip_user = F.sender_id.in_({111111, 222222})
```


---

# FSM, Persistent Storage & `ctx.ask()`

## Declarative `StatesGroup`

```python
from shirdal import Context, State, StatesGroup, command, state, text

class OrderForm(StatesGroup):
    product = State()
    quantity = State()

@bot.on(command("order", prefix="/"))
async def start_order(ctx: Context) -> None:
    await ctx.state.set(OrderForm.product)
    await ctx.reply("Which product would you like?")

@bot.on(state(OrderForm.product) & text)
async def got_product(ctx: Context) -> None:
    await ctx.state.update(product=ctx.text)
    await ctx.state.set(OrderForm.quantity)
    await ctx.reply("How many?")
```

## Multi-State, `ANY_STATE`, and `FSMStrategy`

- Match multiple states at once: `state(OrderForm.product, OrderForm.quantity)`
- Match any active state: `state("*")` or `state(ANY_STATE)`
- Control key isolation with `FSMStrategy` (`USER_IN_CHAT`, `CHAT`, `GLOBAL_USER`, `USER_IN_TOPIC`).

## Persistent Storage with TTL

```python
from shirdal import FSMStrategy, RedisStorage, Shirdal

storage = RedisStorage("redis://localhost:6379/0", fsm_ttl=1800)  # 30 min TTL
bot = Shirdal(adapter, storage=storage, fsm_strategy=FSMStrategy.USER_IN_CHAT)
```

## One-Line Conversations with `await ctx.ask()`

```python
@bot.on(command("feedback", prefix="/"))
async def feedback(ctx: Context) -> None:
    reply_ctx = await ctx.ask("Send your feedback (60s):", timeout=60, filters=F.text)
    await reply_ctx.reply("Thanks! Received.")
```


---

# Middlewares, Anti-Flood & Error Handling

## Middlewares

Register global middlewares with `@bot.use` or router-scoped middlewares with `@router.use`:

```python
import time
from shirdal import Context, NextHandler

@bot.use
async def timing_middleware(ctx: Context, call_next: NextHandler) -> None:
    t0 = time.perf_counter()
    await call_next(ctx)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"Handled {ctx.id} in {elapsed_ms:.1f}ms")
```

## Anti-Flood Protection

`Shirdal` wraps your adapter with `AntiFloodAdapter` by default (`anti_flood=True`), automatically pacing per-chat bursts and retrying `FLOOD_WAIT` errors:

```python
from shirdal import AntiFloodConfig, Shirdal

cfg = AntiFloodConfig(min_interval=0.5, max_wait=30.0)
bot = Shirdal(adapter, flood_config=cfg)
```

## Global Error Handling

```python
@bot.on_error
async def handle_errors(ctx: Context, exc: Exception) -> None:
    await ctx.reply(f"Oops: <code>{exc}</code>")
```


---

# Plugins, Hot-Reload & Scheduler

## Hot-Reloadable Plugins

Point `Shirdal` to a `plugins/` directory with `hot_reload=True` — editing any `.py` plugin file reloads its handlers and scheduled jobs without restarting the bot:

```python
bot = Shirdal(adapter, plugins_dir="plugins", hot_reload=True, reload_interval=1.0)
```

## Periodic & Delayed Tasks

```python
@bot.every(minutes=5, run_immediately=False)
async def cleanup_job() -> None:
    print("Running periodic cleanup...")

bot.after(10.0, lambda: print("10s later!"))
```


---

# MultiBot & Encrypted Storage

## Running Multiple Accounts (`MultiBot`)

```python
from shirdal import BotAPIAdapter, MultiBot, Shirdal, command

bot1 = Shirdal(BotAPIAdapter(TOKEN_1))
bot2 = Shirdal(BotAPIAdapter(TOKEN_2))

fleet = MultiBot([bot1, bot2])

@fleet.on(command("whoami", prefix="/"))
async def whoami(ctx):
    await ctx.reply("Managed by MultiBot!")

fleet.run()
```

## Storage Backends & `EncryptedStorage`

- `SQLiteStorage("bot.sqlite")` — WAL mode + L1 memory cache (FSM + chat cache)
- `RedisStorage("redis://localhost:6379/0", fsm_ttl=1800)` — distributed FSM + chat cache
- `MySQLStorage(...)` — async/pooled MySQL backend
- `EncryptedStorage(inner_storage, SecretBox(key))` — transparently encrypts stored values at rest.


---

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


---

# Migrating from aiogram / Pyrogram

## From `aiogram` v3

| Concept | `aiogram` v3 | `shirdal` |
| :--- | :--- | :--- |
| Router | `Router()` + `dp.include_router()` | `Router()` + `bot.include_router()` |
| Magic Filter | `F.text.startswith("/")` | `F.text.startswith("/")` |
| FSM | `StatesGroup` + `State` + `FSMContext` | `StatesGroup` + `State` + `ctx.state` |
| Quick Reply Prompt | Manual state handlers | `await ctx.ask("Prompt?", timeout=60)` |
| 50MB+ Files | Requires Local Bot API Server | `HybridAdapter(bot_api, mtproto)` (native) |

## From `Pyrogram` / `Telethon`

- Replace `TgCrypto` with **`shircrypt`** (`pip install "shirdal[shircrypt]"` for 4.67x–11.84x faster crypto).
- Handlers receive a unified `ctx: Context` with `ctx.reply()`, `ctx.edit()`, `ctx.reply_media()`, and `ctx.download()`.
