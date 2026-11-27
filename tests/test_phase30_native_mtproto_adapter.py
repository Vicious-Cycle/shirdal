import asyncio
import os
import struct
import unittest

from shirdal import (
    Context,
    EventType,
    FloodWaitError,
    MessageEvent,
    NativeMTProtoAdapter,
    Shirdal,
    TransportAdapter,
    UpdateEvent,
    ChatRef,
    UserRef,
    command,
    incoming,
)
from shirdal.mtproto import (
    BAD_SERVER_SALT_ID,
    MSGS_ACK_ID,
    RPC_ERROR_ID,
    RPC_RESULT_ID,
    AuthKey,
    TLReader,
    TLWriter,
)


async def _read_abridged_frame(reader: asyncio.StreamReader) -> bytes:
    first = (await reader.readexactly(1))[0]
    if first < 127:
        words = first
    else:
        words = int.from_bytes(await reader.readexactly(3), "little")
    return await reader.readexactly(words * 4)


def _write_abridged_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    words = len(payload) // 4
    if words < 127:
        writer.write(bytes([words]) + payload)
    else:
        writer.write(b"\x7f" + words.to_bytes(3, "little") + payload)


class TestPhase30NativeMTProtoAdapter(unittest.IsolatedAsyncioTestCase):
    def test_native_mtproto_satisfies_transport_adapter_protocol(self) -> None:
        adapter = NativeMTProtoAdapter(12345, "hash", auth_key=os.urandom(256))
        self.assertIsInstance(adapter, TransportAdapter)

    async def test_native_mtproto_encrypted_rpc_floodwait_and_shirdal_dispatch(self) -> None:
        auth_key = AuthKey(os.urandom(256))
        salt = 11223344
        call_count = 0

        async def fake_mtproto_server(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            nonlocal call_count
            hdr = await reader.readexactly(1)
            self.assertEqual(hdr, b"\xef")
            try:
                while True:
                    pkt = await _read_abridged_frame(reader)
                    padded = auth_key.decrypt_packet(pkt, from_client=True)
                    r = TLReader(padded)
                    _pkt_salt = r.read_long()
                    sess_id = struct.unpack("<Q", r.read_raw(8))[0]
                    req_msg_id = r.read_long()
                    _seq = r.read_int()
                    msg_len = r.read_int()
                    body = r.read_raw(msg_len)
                    if struct.unpack_from("<I", body, 0)[0] == MSGS_ACK_ID:
                        continue  # client acks are service messages, not RPCs
                    call_count += 1

                    if call_count == 1:
                        # First RPC: return bad_server_salt + rpc_result OK
                        res = TLWriter()
                        res.write_uint(RPC_RESULT_ID)
                        res.write_long(req_msg_id)
                        res.write_raw(b"PONG")
                        resp_body = res.to_bytes()
                    elif call_count == 2:
                        # Second RPC: return FLOOD_WAIT_12 error
                        res = TLWriter()
                        res.write_uint(RPC_RESULT_ID)
                        res.write_long(req_msg_id)
                        res.write_uint(RPC_ERROR_ID)
                        res.write_int(420)
                        res.write_string("FLOOD_WAIT_12")
                        resp_body = res.to_bytes()
                    else:
                        # Any further RPC (like send_message from Shirdal handler): return OK
                        res = TLWriter()
                        res.write_uint(RPC_RESULT_ID)
                        res.write_long(req_msg_id)
                        res.write_raw(b"SENT")
                        resp_body = res.to_bytes()

                    srv_inner = TLWriter()
                    srv_inner.write_long(salt)
                    srv_inner.write_raw(struct.pack("<Q", sess_id))
                    srv_inner.write_long(req_msg_id + 1)
                    srv_inner.write_int(1)
                    srv_inner.write_int(len(resp_body))
                    srv_inner.write_raw(resp_body)
                    enc = auth_key.encrypt_packet(srv_inner.to_bytes(), from_client=False)
                    _write_abridged_frame(writer, enc)
                    await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(fake_mtproto_server, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        adapter = NativeMTProtoAdapter(
            12345,
            "api_hash",
            host="127.0.0.1",
            port=port,
            auth_key=auth_key,
            server_salt=salt,
        )
        async def _no_sync() -> None:  # background updates.getState would shift the scripted RPC order
            return None

        adapter._initial_sync = _no_sync
        bot = Shirdal(adapter, use_uvloop=False, anti_flood=False)
        replies: list[str] = []

        @bot.on(incoming & command("hello", prefix="/"))
        async def on_hello(ctx: Context) -> None:
            sent = await ctx.reply("world!")
            replies.append(sent.text)

        try:
            await adapter.connect()
            res1 = await adapter.invoke_raw(b"\x01\x02\x03\x04")
            self.assertEqual(res1, b"PONG")

            with self.assertRaises(FloodWaitError) as fw:
                await adapter.invoke_raw(b"\x05\x06\x07\x08")
            self.assertEqual(fw.exception.seconds, 12.0)

            # Dispatch incoming update through Shirdal engine -> triggers send_message over encrypted TCP!
            serve_task = asyncio.create_task(bot.serve())
            await adapter.push_update(
                UpdateEvent(
                    type=EventType.NEW_MESSAGE,
                    message=MessageEvent(
                        id=10,
                        chat=ChatRef(id=777, type="private"),
                        sender=UserRef(id=777, first_name="Ali"),
                        text="/hello",
                    ),
                )
            )
            await asyncio.sleep(0.08)
            await bot.stop()
            await serve_task
            self.assertEqual(replies, ["world!"])
        finally:
            await adapter.disconnect()
            server.close()
            await server.wait_closed()
