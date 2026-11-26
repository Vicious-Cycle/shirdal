# FSM, Persistent Storage & `ctx.ask()`

## Declarative `StatesGroup`

```python
from shirdal import Context, State, StatesGroup, command, state, text

class OrderForm(StatesGroup):
    product = State()
    quantity = State()

@bot.on(command("order", prefix="/"))
async def start_order(ctx: Context) -> None:
    await ctx.state.set(OrderForm.product)
    await ctx.reply("Which product would you like?")

@bot.on(state(OrderForm.product) & text)
async def got_product(ctx: Context) -> None:
    await ctx.state.update(product=ctx.text)
    await ctx.state.set(OrderForm.quantity)
    await ctx.reply("How many?")
```

## Multi-State, `ANY_STATE`, and `FSMStrategy`

- Match multiple states at once: `state(OrderForm.product, OrderForm.quantity)`
- Match any active state: `state("*")` or `state(ANY_STATE)`
- Control key isolation with `FSMStrategy` (`USER_IN_CHAT`, `CHAT`, `GLOBAL_USER`, `USER_IN_TOPIC`).

## Persistent Storage with TTL

```python
from shirdal import FSMStrategy, RedisStorage, Shirdal

storage = RedisStorage("redis://localhost:6379/0", fsm_ttl=1800)  # 30 min TTL
bot = Shirdal(adapter, storage=storage, fsm_strategy=FSMStrategy.USER_IN_CHAT)
```

## One-Line Conversations with `await ctx.ask()`

```python
@bot.on(command("feedback", prefix="/"))
async def feedback(ctx: Context) -> None:
    reply_ctx = await ctx.ask("Send your feedback (60s):", timeout=60, filters=F.text)
    await reply_ctx.reply("Thanks! Received.")
```
