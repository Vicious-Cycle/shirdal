# Plugins, Hot-Reload & Scheduler

## Hot-Reloadable Plugins

Point `Shirdal` to a `plugins/` directory with `hot_reload=True` — editing any `.py` plugin file reloads its handlers and scheduled jobs without restarting the bot:

```python
bot = Shirdal(adapter, plugins_dir="plugins", hot_reload=True, reload_interval=1.0)
```

Inside `plugins/ping.py`:

```python
from shirdal import Context, command

def setup(bot) -> None:
    @bot.on(command("ping", prefix="/"))
    async def ping(ctx: Context) -> None:
        await ctx.reply("Pong!")
```

## Periodic & Delayed Tasks

```python
@bot.every(minutes=5, run_immediately=False)
async def cleanup_job() -> None:
    print("Running periodic cleanup...")

# One-off delayed task inside a handler:
bot.after(10.0, lambda: print("10s later!"))
```
