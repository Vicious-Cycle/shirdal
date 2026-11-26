# Changelog

## [1.0.13] - 2026-11-27

### Added
- **Minimal Progressive Startup Banner:** prints `Bot is running...` immediately, followed by a clean single-item-per-line diagnostic card and an in-place live `ping:` line that refreshes every 60 seconds.

### Fixed
- **Native MTProto Bot Auth:** pass required `flags=0` to `auth.importBotAuthorization`.
- **HybridAdapter:** forward `**kwargs` (such as `reply_markup`) in `send_message` and `edit_message`.
- **Crypto Fallback:** guard `cryptography` import so `shircrypt` fallback works even when `_cffi_backend` is unavailable.

## [1.0.7] - 2026-11-26

### Fixed
- **Constructor IDs / layer mismatch:** Native MTProto now serializes every request from the official schema (`mtproto/data/api.tl`, Layer 222) via the new `shirdal.mtproto.tl_runtime`; hand-written IDs (e.g. stale `messages.sendMessage#983f9745`) are no longer used by the adapter.
- **Login:** interactive / programmatic login (`auth.sendCode`, `auth.signIn`, 2FA SRP `auth.checkPassword`, `auth.importBotAuthorization`), sign-up-required detection, persisted authorization; bundled Telegram RSA keys so new sessions can handshake.
- **DC migration:** `PHONE/USER/NETWORK_MIGRATE_X` switch DC; `FILE_MIGRATE_X` uses exported authorization on a file-DC connection.
- **Connection stability:** keepalive (`ping_delay_disconnect`) is actually started, auto-reconnect with pending-request resend, resend after `bad_server_salt` / `bad_msg_notification`, acks for every content-related message (including `rpc_result`).
- **Updates:** full parsing of `updates`, `updatesCombined`, `updateShort*`, new/edit/delete (incl. channel) messages; `getDifference` / `getChannelDifference` results are applied and `pts` state is persisted. Fixed emitting the non-existent `EventType.MESSAGE`.
- **Peer cache:** filled from every update / result; `contacts.resolveUsername` and dialogs fallback; Bot-API style ids (`-chat_id`, `-100channel_id`) so replies in groups no longer go to a user with the same id.
- **Messages & media:** real message ids returned from `send_message` / `send_media` / `send_album`; `send_media` honors `reply_to` and `parse_mode`; big-file uploads, photos vs documents, albums via `sendMultiMedia`; real `download_media`; real `get_chat`; complete `setTyping`, reactions, pin, ban/mute/kick (incl. basic groups); `invoke(method, **params)` builds real TL.


## [1.0.5] - 2026-11-26

### Added
- **Native 5-Layer MTProto 2.0 Core (`shirdal.mtproto`):**
  - `TLReader` / `TLWriter` zero-copy binary codec, `gzip_packed`, and `.tl` schema parser + `@dataclass(slots=True)` code generator (`generate_python_module`).
  - `AES-256-IGE`, MTProto 2.0 KDF, `AuthKey` packet encryption/authentication, Pollard's rho factorization, and 3-step DH `HandshakeSession`.
  - `TCPAbridgedTransport` (`asyncio`), `MTProtoSessionState` (SQLite persistence), and `MTProtoWire` (`msg_container`, `msgs_ack`, `bad_server_salt`, `rpc_result` / `rpc_error`).
  - `PeerCache` (`access_hash` persistence), `UpdateStateTracker` (`pts`/`qts`/`seq` gap detection), and parallel chunked `FileTransferManager`.
  - `NativeMTProtoAdapter` implementing `TransportAdapter` with automatic `FLOOD_WAIT` mapping.
- **Repository & Documentation Polish:** Added `docs/native-mtproto.md`, `SECURITY.md`, GitHub issue/PR templates, and upgraded `README.md` / `README.fa.md`.

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
