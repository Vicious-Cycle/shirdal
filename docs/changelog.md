# Changelog

For full release notes, see [`CHANGELOG.md`](https://github.com/Vicious-Cycle/shirdal/blob/main/CHANGELOG.md) on GitHub.

## Latest Highlights

- **Startup Diagnostics**: Automatic latency (`ping`) measurement, `@username`, `uvloop`, `msgspec`, and `shircrypt` status banner.
- **Native `shircrypt` Integration**: Full MTProto 2.0 KDF + `mtproto2_encrypt_packet` / `mtproto2_decrypt_packet` acceleration.
- **FSM & Conversations**: `FSMStrategy`, multi-state & `ANY_STATE` filters, `MemoryStorage(ttl=...)`, `RedisStorage(fsm_ttl=...)`, and `await ctx.ask()`.
- **Modern Routing & Hybrid Mode**: `Router` trees, zero-dependency magic filter `F`, and `HybridAdapter` for automatic 50MB+ MTProto uploads.
