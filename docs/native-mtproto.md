# Native MTProto 2.0 Core

Shirdal includes a modular, 5-layer native MTProto 2.0 core (`shirdal.mtproto`, **Layer 234**) wired into `NativeMTProtoAdapter`. Every layer is independently testable and decoupled from high-level bot logic.

## Layer Overview

| Layer | Module | Responsibility |
| :--- | :--- | :--- |
| 1. Binary & Schema | `tl_codec.py`, `tl_schema.py`, `tl_runtime.py` | Zero-copy `TLReader`/`TLWriter`, `.tl` parser, Layer 234 `api.tl` runtime serializer |
| 2. Crypto & Handshake | `crypto.py`, `auth.py`, `srp.py`, `rsa_keys.py` | `AES-256-IGE` (with `shircrypt` acceleration), MTProto 2.0 KDF, 3-step DH, 2FA SRP, bundled Telegram RSA keys |
| 3. Transport & Framing | `transport.py`, `session.py`, `sender.py` | `TCPAbridgedTransport` (`TCP_NODELAY`), SQLite `MTProtoSessionState`, keepalive, acks, auto-reconnect & resend |
| 4. State & Transfers | `updates.py`, `files.py` | `PeerCache` (`access_hash` + full dialog paging), `UpdateStateTracker` (`pts`/`qts`/`seq`), parallel `FileTransferManager` |
| 5. Adapter Integration | `native_mtproto_adapter.py` | `NativeMTProtoAdapter` implementing `TransportAdapter`, DC migration, raw `invoke()`, and `FloodWaitError` |

## Using `NativeMTProtoAdapter`

```python
import os
from shirdal import Context, DeviceProfile, NativeMTProtoAdapter, Shirdal, command, outgoing

adapter = NativeMTProtoAdapter(
    int(os.environ["API_ID"]),
    os.environ["API_HASH"],
    session_path="session.sqlite",
    dc_id=2,
    device=DeviceProfile.desktop(),
)

bot = Shirdal(adapter, anti_flood=True)

@bot.on(command("ping") & outgoing)
async def ping(ctx: Context) -> None:
    await ctx.edit("Pong!")
```

## Raw TL Calls, DC Migration & FloodWait

- **Raw TL Calls:** Call any Layer 234 method directly via `await adapter.invoke("messages.getHistory", peer=..., limit=20)` without manual constructor IDs.
- **Automatic DC Migration & 2FA:** `PHONE_MIGRATE_X`, `USER_MIGRATE_X`, `NETWORK_MIGRATE_X`, and `FILE_MIGRATE_X` are handled transparently, along with 2FA SRP (`auth.checkPassword`).
- **Rate Limits:** Telegram `FLOOD_WAIT_X` errors raise `FloodWaitError`, exposing both `.seconds` and `.retry_after`.

## Generating TL Models from `.tl` Files

Use `generate_python_module()` to compile any Telegram `.tl` schema slice into slotted Python dataclasses:

```python
from shirdal.mtproto import generate_python_module

py_source = generate_python_module(open("api.tl", encoding="utf-8").read())
```

## Parallel File Transfers

`FileTransferManager` automatically splits payloads into 512 KiB aligned chunks, computes MD5 for small files (`<= 10 MiB`), and switches to big-file mode (`> 10 MiB`) with bounded `asyncio.Semaphore` concurrency.
