<div align="center">

# Shirdal

**One Python framework for Telegram bots and userbots.**
Write your handlers once, run them on the Bot API or on a native MTProto 2.0 client.

**English** | [فارسی](README.fa.md)

[![PyPI](https://img.shields.io/pypi/v/shirdal.svg?color=007ec6)](https://pypi.org/project/shirdal/)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml/badge.svg)](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

---

## Why Shirdal

Telegram has two very different APIs, and most libraries only cover one of them. Switching means rewriting your bot.

Shirdal puts everything above the network layer (dispatcher, filters, context, FSM, middleware, scheduler, storage) behind a single `TransportAdapter` interface. Your handlers don't know or care what is underneath, so moving from a bot token to a user account is a one-line change.

```text
   Handlers · Filters · FSM · Middleware · Scheduler · Plugins · Storage
                                  │
                           TransportAdapter
        ┌──────────────┬──────────┴────────┬──────────────────┐
        ▼              ▼                   ▼                  ▼
  BotAPIAdapter  NativeMTProtoAdapter  Telethon / Hydrogram  MockAdapter
  (HTTP + webhook)  (built-in MTProto 2.0)   (wrappers)      (offline tests)
```

## Features

**Framework**
- Typed `Context` with helpers such as `reply`, `edit`, `react`, `pin`, `download`, `reply_media` and `typing`
- Composable filters (`&`, `|`, `~`, regex, commands, callbacks)
- Multi-step conversations with `StatesGroup` (FSM)
- Middleware, `@bot.every()` scheduler, and `MultiBot` for running several accounts at once
- Hot-reloadable plugins: edit a file in `plugins/` and it reloads without a restart
- Storage backends: SQLite, Redis, MySQL, plus `EncryptedStorage` for sensitive data
- `AntiFloodAdapter` with automatic `FLOOD_WAIT` handling and per-chat pacing

**Bot API**
- Dependency-free HTTP client with keep-alive (optional `msgspec` for faster JSON)
- Built-in `asyncio` webhook server with secret-token verification and a `/health` endpoint
- Support for recent Bot API features: colored buttons, custom emoji, rich messages, ephemeral replies, draft streaming, member tags and topics

**Native MTProto 2.0**
- Pure Python implementation: TL codec and schema code generator, AES-256-IGE, key exchange, encrypted sessions, TCP transport
- Login with code, 2FA password or bot token; DC migration; reconnects and update gap recovery
- Peer cache, chunked parallel file upload and download
- Optional Rust acceleration through [`shircrypt`](https://github.com/Vicious-Cycle/shircrypt)

## Installation

```bash
pip install shirdal
```

Optional extras:

```bash
pip install "shirdal[fast]"       # uvloop + msgspec
pip install "shirdal[shircrypt]"  # Rust-accelerated AES-IGE
pip install "shirdal[telethon]"   # Telethon adapter
pip install "shirdal[hydrogram]"  # Hydrogram adapter
pip install "shirdal[redis]"      # Redis storage
pip install "shirdal[mysql]"      # MySQL storage
```

Requires Python 3.11 or newer.

## Quick start

### Bot API

```python
import os
from shirdal import (
    BotAPIAdapter, ButtonStyle, Context, Shirdal,
    button, callback, command, incoming, inline_keyboard,
)

bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))

@bot.on(incoming & command("start", prefix="/"))
async def start(ctx: Context) -> None:
    kb = inline_keyboard([[
        button("Approve", "act:ok", style=ButtonStyle.SUCCESS),
        button("Reject", "act:no", style=ButtonStyle.DANGER),
    ]])
    await ctx.reply("<b>Choose an action:</b>", reply_markup=kb)

@bot.on_callback(callback(prefix="act:"))
async def on_action(ctx: Context) -> None:
    await ctx.answer("Done")

if __name__ == "__main__":
    bot.run()
```

### Userbot (native MTProto)

```python
import os
from shirdal import Context, DeviceProfile, NativeMTProtoAdapter, Shirdal, command, outgoing

adapter = NativeMTProtoAdapter(
    int(os.environ["API_ID"]),
    os.environ["API_HASH"],
    session_path="account.sqlite",
    device=DeviceProfile.desktop(),
)

bot = Shirdal(adapter, plugins_dir="plugins", hot_reload=True)

@bot.on(command("ping") & outgoing)
async def ping(ctx: Context) -> None:
    await ctx.edit("Pong!", auto_delete=10)

if __name__ == "__main__":
    bot.run()
```

More runnable examples live in [`examples/`](examples).

## Command line

```bash
shirdal new my_bot --adapter botapi   # scaffold a project (botapi, telethon, hydrogram, mock)
shirdal doctor                        # check Python version and optional dependencies
shirdal run main.py                   # run an entry script
```

## Testing your bot

`MockAdapter` runs your handlers fully offline, with no network and no Telegram account. Push fake updates in, assert on what was sent out. The project's own test suite is built this way:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Production notes

- Enable logging to see which crypto backend is active at startup:
  ```python
  import logging
  logging.basicConfig(level=logging.INFO)
  # shirdal 1.0.x started | crypto backend: shircrypt-rust (v1.0.x)
  ```
- Use `WebhookServer` behind a reverse proxy (nginx, Caddy) and always set a secret token.
- Keep `.sqlite` session files private. They contain your account's authorization key.

## Project status

Shirdal is young. The Bot API side and the framework layer are covered by an automated test suite. The native MTProto client is a from-scratch implementation that is mostly tested against simulated servers, so expect rough edges on real accounts and please report them. The MTProto code has not had an independent security audit; for high-stakes accounts, prefer an established client such as Telethon through the provided adapter.

## Documentation

- [Getting started](docs/getting-started.md)
- [Bot API features](docs/bot-api.md)
- [Rich messages](docs/rich-messages.md)
- [Native MTProto core](docs/native-mtproto.md)
- [Webhook and deployment](docs/webhook-and-deployment.md)
- [مستندات فارسی](docs/fa/README.md)

## Contributing

Bug reports, ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). For security issues, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

[LGPL-3.0-or-later](LICENSE)
