# Getting Started

Shirdal requires **Python 3.11+**. The core framework and `BotAPIAdapter` have zero required third-party dependencies.

## Installation

```bash
pip install shirdal
```

Optional extras:

```bash
pip install "shirdal[fast]"      # uvloop + msgspec JSON acceleration
pip install "shirdal[telethon]"  # Telethon MTProto adapter
pip install "shirdal[hydrogram]" # Hydrogram MTProto adapter
pip install "shirdal[redis]"     # Redis FSM & cache backend
pip install "shirdal[mysql]"     # MySQL FSM & cache backend
pip install "shirdal[crypto]"    # EncryptedStorage (SecretBox)
```

## Scaffolding with the CLI

Create a Bot API project:

```bash
shirdal new my_bot --adapter botapi
cd my_bot
shirdal doctor
shirdal run main.py
```

Create a Telethon selfbot or bot project:

```bash
shirdal new my_client --adapter telethon
```

## Core Architecture

Every `Shirdal` instance wraps a `TransportAdapter`:

- `BotAPIAdapter` — Keep-Alive HTTP/HTTPS client for standard Telegram bots (long polling or built-in `WebhookServer`).
- `TelethonAdapter` — MTProto client supporting both user accounts (`StringSession`) and `bot_token`.
- `HydrogramAdapter` — Hydrogram MTProto client with automatic Pyrogram fallback and `bot_token` support.
- `MockAdapter` — In-memory adapter for deterministic unit tests without network calls.

Handlers receive a `Context` (`ctx`) object with `ctx.reply()`, `ctx.edit()`, `ctx.answer()`, `ctx.state`, `ctx.args`, and `ctx.match`, and can be filtered with `command`, `regex`, `callback`, `state`, `private`, `group`, `incoming`, `outgoing`, `reply`, and `text` using `&`, `|`, and `~`.
