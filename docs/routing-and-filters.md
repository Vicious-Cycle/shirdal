# Routers & Magic Filter `F`

## Modular Routers

Split your bot into clean modules using `Router`, then attach them to `Shirdal` (or nest routers inside each other):

```python
from shirdal import F, Router, command

admin_router = Router("admin")

@admin_router.use
async def admin_only(ctx, call_next):
    if ctx.sender_id != 123456789:
        return
    await call_next(ctx)

@admin_router.on(command("stats", prefix="/"))
async def stats(ctx):
    await ctx.reply("All systems operational.")

# In main.py:
# bot.include_router(admin_router)
```

## Magic Filter `F`

`F` lets you write concise, zero-dependency inline filters that compose seamlessly with `&`, `|`, and `~`:

```python
from shirdal import F

yt_private = F.text.startswith("https://") & F.text.contains("youtu") & (F.message.chat.type == "private")
ok_btn = F.callback_data.startswith("act:")
vip_user = F.sender_id.in_({111111, 222222})
```
