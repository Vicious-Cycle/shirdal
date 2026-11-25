<div align="center">

# Shirdal

**A transport-agnostic, context-first Python framework for Telegram — featuring a built-in Bot API 10.5 engine and a native MTProto 2.0 core.**

**English** | [فارسی](README.fa.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/shirdal.svg?color=007ec6)](https://pypi.org/project/shirdal/)
[![CI](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml/badge.svg)](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

---

Most Telegram frameworks force a choice: either use a Bot API library that cannot touch MTProto, or an MTProto client with heavy, tightly-coupled internals. **Shirdal** decouples your application logic (`Dispatcher`, `Context`, filters, `FSM`, `AntiFlood`, hot-reload plugins, and storage) behind a single `TransportAdapter` protocol—and ships both a **zero-HTTP-dependency Bot API 10.5 engine** and a **clean 5-layer native MTProto 2.0 core**.

## Architecture

```text
  Your Handlers & Plugins (Context, Filters, FSM, Scheduler, MultiBot)
                                │
                        TransportAdapter
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
   BotAPIAdapter      NativeMTProtoAdapter    Telethon / Hydrogram / Mock
 (HTTP Keep-Alive +   (TL Codec, AES-256-IGE,   (Legacy MTProto wrappers
  WebhookServer)       TCP Abridged, PeerCache)  & offline test adapter)
```

## Why Shirdal?

| Capability | Shirdal | Pyrogram (Archived) | Telethon | aiogram |
| :--- | :--- | :--- | :--- | :--- |
| Transport independence | Bot API + Native MTProto + Wrappers + Mock | MTProto only | MTProto only | Bot API only |
| Bot API 9.4–10.5 (Colored Buttons, Custom Emoji, Rich Messages, Ephemeral, Draft Streaming) | Native & typed | Partial / raw | N/A | Requires external HTTP stack |
| Built-in Webhook Server | `asyncio` HTTP/1.1 (`WebhookServer`, zero deps) | N/A | N/A | Requires aiohttp / FastAPI |
| Native MTProto 2.0 Core | 5-layer modular (`shirdal.mtproto`) + `tlgen` | Monolithic | Monolithic | N/A |
| Production Primitives | `AntiFlood`, `SQLite/Redis/MySQL`, `SecretBox`, Hot-Reload, `MultiBot` | Manual | Manual | FSM + Middleware |

## Key Features

- **Built-in Bot API Engine (`BotAPIAdapter`):** Keep-Alive HTTP/HTTPS client with optional `msgspec` JSON acceleration and a built-in `asyncio` `WebhookServer` (with `X-Telegram-Bot-Api-Secret-Token` verification and `GET /health`).
- **Bot API 10.5 Ready:**
  - **Colored & Icon Buttons:** `ButtonStyle` (`primary`, `success`, `danger`), `icon` / `icon_custom_emoji_id`, `disabled`, `copy_text`, `web_app_url`, `reply_button()`, and `reply_keyboard(..., force_reply=True)`.
  - **Premium Emoji & Localized Time:** `custom_emoji()`, `custom_emoji_entity()`, `date_time()`, and `date_time_entity()`.
  - **Ephemeral Group Replies & AI Streaming:** `ctx.reply_ephemeral()`, `async with ctx.stream()` (`sendMessageDraft`), and `async with ctx.stream_rich()` (`sendRichMessageDraft`).
  - **Rich Messages:** `ctx.reply_rich()` and typed block builders (`rich_heading`, `rich_table`, `rich_details`, `rich_blockquote`, `rich_code`, `rich_math`, `rich_buttons`, `rich_thinking`).
  - **Group Tags, Topics & Settings:** `ctx.set_member_tag()`, `create_forum_topic()`, and `set_my_settings()`.
- **Native MTProto 2.0 Core (`shirdal.mtproto` & `NativeMTProtoAdapter`):**
  - Zero-copy `TLReader`/`TLWriter` + `.tl` schema codegen (`generate_python_module`) producing `@dataclass(slots=True)` models.
  - `AES-256-IGE`, MTProto 2.0 KDF, `AuthKey`, Pollard's rho factorization, and 3-step DH `HandshakeSession`.
  - `TCPAbridgedTransport`, `MTProtoSessionState` (SQLite persistence), `MTProtoWire` (`msg_container`, `msgs_ack`, `bad_server_salt`, `gzip_packed`, `rpc_result`).
  - `PeerCache` (`access_hash` persistence), `UpdateStateTracker` (`pts`/`qts`/`seq` gap detection), and parallel chunked `FileTransferManager`.
- **Resilience & Tooling:** `AntiFloodAdapter` with `FloodWaitError` recovery, live hot-reload `plugins/`, `StatesGroup` FSM, `EncryptedStorage` (`Encrypt-then-MAC`), `@bot.every()` scheduler, `MultiBot`, and `shirdal` CLI (`new`, `doctor`, `run`).

## Installation

```bash
pip install shirdal              # Includes Bot API 10.5 + Native MTProto 2.0 (cryptography)

# Optional extras
pip install "shirdal[fast]"      # uvloop + msgspec JSON speedups
pip install "shirdal[telethon]"  # Telethon adapter
```

## Quickstart: Modern Bot API

```python
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
    incoming,
    inline_keyboard,
)

bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))

@bot.on(incoming & command("start", prefix="/"))
async def start(ctx: Context) -> None:
    badge = custom_emoji("5368324170671202286", "✨")
    kb = inline_keyboard([
        [
            button("Approve", "act:ok", style=ButtonStyle.SUCCESS, icon="5368324170671202286"),
            button("Reject", "act:no", style=ButtonStyle.DANGER),
        ]
    ])
    await ctx.reply(f"{badge} <b>Select an action:</b>", reply_markup=kb)

@bot.on_callback(callback(prefix="act:"))
async def on_action(ctx: Context) -> None:
    await ctx.answer("Recorded")
    await ctx.reply_ephemeral(f"Triggered: <code>{ctx.callback_data}</code>")

if __name__ == "__main__":
    bot.run()
```

## Quickstart: Native MTProto 2.0

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
    await ctx.edit("Pong from Native MTProto 2.0", auto_delete=10)

if __name__ == "__main__":
    bot.run()
```

## Documentation

- [Getting Started & CLI](docs/getting-started.md)
- [Bot API 10.5 Features](docs/bot-api.md)
- [Rich Messages Guide](docs/rich-messages.md)
- [Native MTProto 2.0 Core](docs/native-mtproto.md)
- [Webhook Server & Deployment](docs/webhook-and-deployment.md)
- [مستندات کامل فارسی](docs/fa/README.md)

## Running Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Security, Contributing & License

- Security vulnerabilities: see [SECURITY.md](SECURITY.md)
- Contributing guidelines: see [CONTRIBUTING.md](CONTRIBUTING.md)
- License: [LGPL-3.0-or-later](LICENSE)
