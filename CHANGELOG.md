# Changelog

## [1.0.0] - 2026-11-26

### Added
- **Core Adapter Layer:** `TransportAdapter` protocol with `MockAdapter`, `TelethonAdapter`, and `HydrogramAdapter`.
- **Context-First Engine:** `Context` (`reply`, `edit`, `send`, `reply_media`, `download`, `react`, `pin`, `ban`, `unban`, `mute`, `kick`, `get_chat`, `typing`, `auto_delete`).
- **Composable Filters:** `command`, `regex`, `state`, `outgoing`, `incoming`, `private`, `group`, `reply`, `text` with `&`, `|`, `~`.
- **Anti-Flood Guard:** `AntiFloodAdapter` with per-chat pacing, global cooldown, and automatic `FloodWaitError` recovery.
- **Hot-Reload Plugins:** `PluginManager` with `setup(bot)`/`teardown(bot)` and live file-mtime watching without disconnecting.
- **Middleware & FSM:** Onion-style `Middleware` pipeline and `StatesGroup` / `FSMStorage`.
- **Storage & Encryption:** `SQLiteStorage` (WAL + L1 cache), `RedisStorage`, and `EncryptedStorage` (`SecretBox`).
- **MultiBot & Scheduler:** Concurrent `MultiBot` fleet runner, `@bot.every(...)` periodic scheduler, and `@bot.on_error`.
- **Developer CLI:** `shirdal new`, `shirdal doctor`, and `shirdal run`.
