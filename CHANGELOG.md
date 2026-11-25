# Changelog

## [1.0.1] - 2026-11-26

### Added
- **Zero-Dependency `BotAPIAdapter` & `WebhookServer`:** Native Keep-Alive Telegram Bot API client with optional `msgspec` acceleration, `set_webhook()` / `delete_webhook()`, and an `asyncio` HTTP/1.1 `WebhookServer` with `X-Telegram-Bot-Api-Secret-Token` verification and `/health` endpoint.
- **Colored Buttons & Custom Emoji (Bot API 9.4 / 10.3):** `ButtonStyle` (`primary`, `success`, `danger`), `icon` / `icon_custom_emoji_id`, `disabled`, `copy_text`, `web_app_url`, `reply_button()`, `reply_keyboard()` (with `force_reply`), `custom_emoji()`, `custom_emoji_entity()`, `date_time()`, and `date_time_entity()`.
- **Ephemeral Messages & Live Draft Streaming (Bot API 9.5 / 10.2–10.4):** `ctx.reply_ephemeral()`, `send_ephemeral_message()`, `edit_ephemeral_message()`, `delete_ephemeral_message()`, `send_message_draft()`, and `async with ctx.stream()` (`DraftStream`).
- **Rich Messages (Bot API 10.1–10.5):** `send_rich_message()`, `send_rich_message_draft()`, `ctx.reply_rich()`, `async with ctx.stream_rich()` (`RichDraftStream`), `edit_message(..., rich_message=...)`, and block builders (`rich_message`, `rich_heading`, `rich_paragraph`, `rich_table`, `rich_details`, `rich_blockquote`, `rich_code`, `rich_math`, `rich_buttons`, `rich_divider`, `rich_footer`, `rich_thinking`).
- **Group Tags, Private Topics & Bot Settings (Bot API 9.4–10.5):** `ctx.set_member_tag()`, `set_chat_member_tag()`, `create_forum_topic()`, and `set_my_settings()`.
- **Inline Keyboards & Callbacks:** `callback()` filter, `@bot.on_callback()`, `ctx.answer()`, and `reply_markup` support.
- **`Shirdal` Primary Client & MTProto Updates:** Renamed `SelfBot` to `Shirdal` (keeping `SelfBot = Shirdal` alias), added `--adapter botapi` to `shirdal new`, and added `bot_token` with Pyrogram fallback to `TelethonAdapter` and `HydrogramAdapter`.

## [1.0.0] - 2026-11-26

### Added
- **Core Adapter Layer:** `TransportAdapter` protocol with `MockAdapter`, `TelethonAdapter`, and `HydrogramAdapter`.
- **Context-First Engine:** `Context` (`reply`, `edit`, `send`, `reply_media`, `download`, `react`, `pin`, `ban`, `unban`, `mute`, `kick`, `get_chat`, `typing`, `auto_delete`).
- **Composable Filters:** `command`, `regex`, `state`, `outgoing`, `incoming`, `private`, `group`, `reply`, `text` with `&`, `|`, `~`.
- **Anti-Flood Guard:** `AntiFloodAdapter` with per-chat pacing, global cooldown, and automatic `FloodWaitError` recovery.
- **Hot-Reload Plugins:** `PluginManager` with `setup(bot)`/`teardown(bot)` and live file-mtime watching without disconnecting.
- **Middleware & FSM:** Onion-style `Middleware` pipeline and `StatesGroup` / `FSMStorage`.
- **Storage & Encryption:** `SQLiteStorage` (WAL + L1 cache), `RedisStorage`, `MySQLStorage`, and `EncryptedStorage` (`SecretBox`).
- **MultiBot & Scheduler:** Concurrent `MultiBot` fleet runner, `@bot.every(...)` periodic scheduler, and `@bot.on_error`.
- **Developer CLI:** `shirdal new`, `shirdal doctor`, and `shirdal run`.
