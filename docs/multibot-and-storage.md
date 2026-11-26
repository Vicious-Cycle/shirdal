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
