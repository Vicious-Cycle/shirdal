# Webhook Server & Production Deployment

## Built-in Webhook Server

`BotAPIAdapter` includes a zero-dependency `asyncio` HTTP/1.1 `WebhookServer` (with optional `msgspec` JSON parsing), so you do not need FastAPI, Starlette, or aiohttp to receive Telegram webhook updates:

```python
import asyncio
import os
from shirdal import BotAPIAdapter, Context, Shirdal, command, incoming

adapter = BotAPIAdapter(os.environ["BOT_TOKEN"])
bot = Shirdal(adapter)

@bot.on(incoming & command("ping", prefix="/"))
async def ping(ctx: Context) -> None:
    await ctx.reply("pong")

async def main() -> None:
    await adapter.connect()
    await adapter.set_webhook(
        "https://bot.example.com/tg-webhook",
        secret_token=os.environ["WEBHOOK_SECRET"],
    )
    server = adapter.create_webhook_server(
        host="0.0.0.0",
        port=8080,
        path="/tg-webhook",
        secret_token=os.environ["WEBHOOK_SECRET"],
    )
    await server.start()
    try:
        async for update in adapter.listen():
            await bot.dispatcher.dispatch(update, adapter)
    finally:
        await server.stop()
        await adapter.disconnect()

asyncio.run(main())
```

The server exposes:
- `POST <path>` — Validates `X-Telegram-Bot-Api-Secret-Token` (returns `403` on mismatch), normalizes the update, and enqueues it for `adapter.listen()`.
- `GET /health` — Returns `200 {"ok": true, "status": "healthy"}` for load balancer / container health checks.

## Anti-Flood & Storage Backends

- **Anti-Flood:** Enabled by default on `Shirdal` via `AntiFloodAdapter`, providing per-chat pacing and automatic `FloodWaitError` recovery.
- **Storage:** Choose `SQLiteStorage("bot.db")` (WAL mode + L1 RAM cache), `RedisStorage`, `MySQLStorage`, or wrap any backend with `EncryptedStorage` (`SecretBox`).
