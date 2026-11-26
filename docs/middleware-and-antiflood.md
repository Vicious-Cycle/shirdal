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
