# Native MTProto 2.0 Core

Shirdal includes a modular, 5-layer native MTProto 2.0 core (`shirdal.mtproto`) wired into `NativeMTProtoAdapter`. Every layer is independently testable and decoupled from high-level bot logic.

## Layer Overview

| Layer | Module | Responsibility |
| :--- | :--- | :--- |
| 1. Binary & Schema | `tl_codec.py`, `tl_schema.py` | Zero-copy `TLReader`/`TLWriter`, `gzip_packed`, `.tl` parser, `@dataclass(slots=True)` codegen |
| 2. Crypto & Handshake | `crypto.py`, `auth.py` | `AES-256-IGE`, MTProto 2.0 KDF, `AuthKey`, Pollard's rho, 3-step DH `HandshakeSession` |
| 3. Transport & Framing | `transport.py`, `session.py` | `TCPAbridgedTransport`, `MTProtoSessionState` (SQLite), `MTProtoWire`, `msg_container`, `bad_server_salt` |
| 4. State & Transfers | `updates.py`, `files.py` | `PeerCache` (`access_hash`), `UpdateStateTracker` (`pts`/`qts`/`seq`), parallel `FileTransferManager` |
| 5. Adapter Integration | `native_mtproto_adapter.py` | `NativeMTProtoAdapter` implementing `TransportAdapter` + `FLOOD_WAIT` mapping |

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

## Generating TL Models from `.tl` Files

Use `generate_python_module()` to compile any Telegram `.tl` schema slice into slotted Python dataclasses:

```python
from shirdal.mtproto import generate_python_module

py_source = generate_python_module(open("api.tl", encoding="utf-8").read())
```

## Parallel File Transfers

`FileTransferManager` automatically splits payloads into 512 KiB aligned chunks, computes MD5 for small files (`<= 10 MiB`), and switches to big-file mode (`> 10 MiB`) with bounded `asyncio.Semaphore` concurrency.
