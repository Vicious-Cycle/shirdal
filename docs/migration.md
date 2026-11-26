# Migrating from aiogram / Pyrogram

## From `aiogram` v3

| Concept | `aiogram` v3 | `shirdal` |
| :--- | :--- | :--- |
| Router | `Router()` + `dp.include_router()` | `Router()` + `bot.include_router()` |
| Magic Filter | `F.text.startswith("/")` | `F.text.startswith("/")` |
| FSM | `StatesGroup` + `State` + `FSMContext` | `StatesGroup` + `State` + `ctx.state` |
| Quick Reply Prompt | Manual state handlers | `await ctx.ask("Prompt?", timeout=60)` |
| 50MB+ Files | Requires Local Bot API Server | `HybridAdapter(bot_api, mtproto)` (native) |

## From `Pyrogram` / `Telethon`

- Replace `TgCrypto` with **`shircrypt`** (`pip install "shirdal[shircrypt]"` for 4.67x–11.84x faster crypto).
- Handlers receive a unified `ctx: Context` with `ctx.reply()`, `ctx.edit()`, `ctx.reply_media()`, and `ctx.download()`.
