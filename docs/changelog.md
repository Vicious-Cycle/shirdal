# Changelog

For full release notes, see [`CHANGELOG.md`](https://github.com/Vicious-Cycle/shirdal/blob/main/CHANGELOG.md) on GitHub.

## [1.0.16]

- **Native MTProto Peers:** Fixed `PEER_ID_INVALID` for users and chats outside the first 200 dialogs — `_input_peer` now pages through all dialogs with a 5-minute per-peer cooldown.
- **`FloodWaitError.retry_after`:** Added `.retry_after` property as an alias of `.seconds`.

## [1.0.14]

- **Routing & Decorators:** Added `on_command` shortcut on `Shirdal` and `Router` (incoming `/` commands by default, configurable for selfbots) and flexible `@bot.on_message` / `@bot.on_message(filter)` syntax.
- **Rich Submodule:** Added `shirdal.rich` re-exporting Rich Messages and keyboard builders.
- **Startup & Performance:** Lazy PEP 562 exports in `shirdal.__init__`, non-blocking startup banner/ping probe, `happy_eyeballs_delay=0.25` + `TCP_NODELAY` on MTProto transport, thread-safe `LifoQueue` pool in `BotAPIAdapter`, and `EventType`-indexed `Dispatcher` routes.

## [1.0.13]

- **Progressive Startup Banner:** Prints `Bot is running...` immediately, followed by active runtime diagnostics (`uvloop`, `msgspec`, `shircrypt`) and an in-place live `ping:` line refreshed every 60 seconds.
- **Fixes:** Passed `flags=0` to `auth.importBotAuthorization`, forwarded `**kwargs` (e.g. `reply_markup`) in `HybridAdapter`, and guarded `cryptography` imports for `shircrypt`-only environments.

## Earlier Highlights

- **Native MTProto 2.0 (Layer 234):** Schema-driven `tl_runtime`, bundled Telegram RSA keys, 2FA SRP, automatic DC migration (`PHONE/USER/NETWORK/FILE_MIGRATE_X`), and parallel chunked file transfers.
- **FSM & Conversations:** `FSMStrategy`, multi-state & `ANY_STATE` filters, `MemoryStorage(ttl=...)`, `RedisStorage(fsm_ttl=...)`, and `await ctx.ask()`.
- **Modern Routing & Hybrid Mode:** `Router` trees, zero-dependency magic filter `F`, and `HybridAdapter` for automatic 50MB+ MTProto uploads.
