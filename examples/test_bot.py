"""Minimal test bot for verifying Shirdal connectivity with Telegram.

Usage (Bot API):
    BOT_TOKEN="123456:ABC..." python3 examples/test_bot.py

Usage (Telethon userbot / selfbot):
    ADAPTER=telethon API_ID=12345 API_HASH="..." SESSION_NAME="test_session" python3 examples/test_bot.py
"""

from __future__ import annotations

import os
import time

from shirdal import BotAPIAdapter, Context, Shirdal, TelethonAdapter, command


def build_adapter():
    mode = os.getenv("ADAPTER", "botapi").lower()
    if mode == "telethon":
        api_id = int(os.environ["API_ID"])
        api_hash = os.environ["API_HASH"]
        session = os.getenv("SESSION_NAME", "test_session")
        return TelethonAdapter(session, api_id, api_hash)

    token = os.environ["BOT_TOKEN"]
    return BotAPIAdapter(token)


app = Shirdal(build_adapter())


@app.on(command("start"))
async def on_start(ctx: Context) -> None:
    await ctx.reply("Shirdal test bot is online!")


@app.on(command("ping"))
async def on_ping(ctx: Context) -> None:
    t0 = time.perf_counter()
    msg = await ctx.reply("Pong...")
    ms = (time.perf_counter() - t0) * 1000
    await msg.edit(f"Pong! `{ms:.1f} ms`")


if __name__ == "__main__":
    app.run()
