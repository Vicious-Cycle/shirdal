<div align="center">

<img src="docs/assets/logo-banner.png" alt="Shirdal Logo" width="460" />

**One Python Framework for Telegram Bots and Userbots**

[Documentation](https://vicious-cycle.github.io/shirdal/) • [Benchmarks](https://github.com/Vicious-Cycle/shircrypt#benchmarks) • [Download Docs (.md)](https://vicious-cycle.github.io/shirdal/shirdal-docs.md) • [فارسی](README.fa.md)

[![CI](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml/badge.svg)](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shirdal.svg?color=d4a843)](https://pypi.org/project/shirdal/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%2B-3776AB.svg)](https://www.python.org/downloads/)
[![Crypto](https://img.shields.io/badge/crypto-shircrypt%204.67x-d4a843.svg)](https://github.com/Vicious-Cycle/shircrypt)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

---

## Shirdal

> Modern, context-first asynchronous framework for Telegram Bot API 10.5 and Native MTProto 2.0 in Python

Write your handlers once and run them on the **Bot API**, a **Native MTProto 2.0** client, or **both at the same time** via `HybridAdapter` — with full support for Bot API 10.5 (colored buttons, custom emoji, rich messages, live draft streaming) and 50MB+ MTProto uploads.

```python
import os
from shirdal import BotAPIAdapter, Context, F, Router, Shirdal

router = Router("main")

@router.on_command("start")
async def start(ctx: Context) -> None:
    reply_ctx = await ctx.ask("What is your name?", timeout=60, filters=F.text)
    await reply_ctx.reply(f"Hello <b>{reply_ctx.text}</b>!")

if __name__ == "__main__":
    bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))
    bot.include_router(router)
    bot.run()
```

## Key Features

- **Ready:** Install `shirdal` with `pip` and start building bots or userbots right away — zero required external HTTP or crypto dependencies.
- **Hybrid:** Run on `BotAPIAdapter` for inline buttons and webhooks while `HybridAdapter` automatically routes files `> 50 MiB` through `NativeMTProtoAdapter`.
- **Fast:** Boosted by [`shircrypt`](https://github.com/Vicious-Cycle/shircrypt), a memory-safe Rust crypto extension (**4.67x faster** on average than `TgCrypto`, up to **11.84x** on AES-CTR) with optional `uvloop` and `msgspec`.
- **Modern:** Modular `Router`s, zero-dependency magic filter `F`, `StatesGroup` FSM with Redis/SQLite TTL, and one-line `await ctx.ask()` conversations.
- **Type-hinted:** Fully typed `Context`, filters, adapters, and `py.typed` marker for first-class IDE autocomplete and `mypy`/`pyright` support.
- **Resilient:** Built-in `AntiFloodAdapter`, hot-reloadable plugins, `@bot.every()` scheduler, and offline testing with `MockAdapter`.

## Installing

**Stable version**

```bash
pip install shirdal
```

**Dev version**

```bash
pip install git+https://github.com/Vicious-Cycle/shirdal.git
```

**Optional dependencies**

```bash
pip install "shirdal[fast]"       # uvloop + msgspec + shircrypt (4.67x faster crypto)
pip install "shirdal[shircrypt]"  # Rust-accelerated AES-IGE / CTR / KDF
pip install "shirdal[redis]"      # Distributed Redis FSM & chat cache
pip install "shirdal[telethon]"   # Telethon adapter
```

## Resources

- Check out the [**Documentation**](https://vicious-cycle.github.io/shirdal/) for full guides, `HybridAdapter`, `FSM`, and auto-generated API Reference.
- Download the [**Full Docs (.md)**](https://vicious-cycle.github.io/shirdal/shirdal-docs.md) for offline reading or AI assistants.
- Explore [**shircrypt**](https://github.com/Vicious-Cycle/shircrypt) for Rust MTProto 2.0 cryptography benchmarks.
- Contributions and security reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

[LGPL-3.0-or-later](LICENSE)
