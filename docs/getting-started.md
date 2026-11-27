# Getting Started

Shirdal requires **Python 3.11+**. `BotAPIAdapter` requires zero external HTTP libraries, and `cryptography` is included out of the box for `NativeMTProtoAdapter` and `EncryptedStorage`.

## Installation

```bash
pip install shirdal
```

Optional extras:

```bash
pip install "shirdal[fast]"      # uvloop + msgspec + shircrypt Rust acceleration
pip install "shirdal[telethon]"  # Telethon MTProto adapter
pip install "shirdal[hydrogram]" # Hydrogram MTProto adapter
pip install "shirdal[redis]"     # Redis FSM & cache backend
pip install "shirdal[mysql]"     # MySQL FSM & cache backend
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

- `BotAPIAdapter` — Keep-Alive HTTP/HTTPS client for Bot API 10.5 (long polling or built-in `WebhookServer`).
- `NativeMTProtoAdapter` — Built-in MTProto 2.0 client (Layer 234) for user accounts and bots with `shircrypt` Rust acceleration.
- `HybridAdapter` — Runs Bot API and `NativeMTProtoAdapter` side by side, automatically routing `> 50 MiB` media uploads through MTProto.
- `TelethonAdapter` — MTProto client supporting both user accounts (`StringSession`) and `bot_token`.
- `HydrogramAdapter` — Hydrogram MTProto client with automatic Pyrogram fallback and `bot_token` support.
- `MockAdapter` — In-memory adapter for deterministic unit tests without network calls.

Organize handlers with modular `Router`s, `@router.on_command("start")`, and `await ctx.ask()` conversations. Handlers receive a `Context` (`ctx`) object with `ctx.reply()`, `ctx.edit()`, `ctx.answer()`, `ctx.state`, `ctx.args`, and `ctx.match`, and can be filtered with the magic filter `F` (`F.text.startswith(...)`) or classic combinators (`command`, `regex`, `callback`, `state`, `private`, `group`, `incoming`, `outgoing`, `reply`, `text`) using `&`, `|`, and `~`.
