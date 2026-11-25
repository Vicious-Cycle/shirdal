import asyncio
import os
import struct
import tempfile
import unittest
from pathlib import Path

from shirdal.mtproto import (
    BAD_SERVER_SALT_ID,
    RPC_ERROR_ID,
    RPC_RESULT_ID,
    AuthKey,
    MTProtoRPCError,
    MTProtoSessionState,
    MTProtoWire,
    TCPAbridgedTransport,
    TLReader,
    TLWriter,
    pack_gzip,
)


class TestPhase28MTProtoTransportSession(unittest.IsolatedAsyncioTestCase):
    async def test_tcp_abridged_transport_short_and_extended_frames(self) -> None:
        received: list[bytes] = []

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            header = await reader.readexactly(1)
            self.assertEqual(header, b"\xef")
            for _ in range(2):
                first = (await reader.readexactly(1))[0]
                if first < 127:
                    words = first
                else:
                    words = int.from_bytes(await reader.readexactly(3), "little")
                data = await reader.readexactly(words * 4)
                received.append(data)
                # Echo back using abridged framing
                if words < 127:
                    writer.write(bytes([words]) + data)
                else:
                    writer.write(b"\x7f" + words.to_bytes(3, "little") + data)
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        transport = TCPAbridgedTransport("127.0.0.1", port)
        try:
            await transport.connect()
            self.assertTrue(transport.is_connected)

            small = b"ABCD" * 5  # 20 bytes -> 5 words (< 127)
            large = b"XYZW" * 200  # 800 bytes -> 200 words (>= 127)
            await transport.send(small)
            self.assertEqual(await transport.recv(), small)

            await transport.send(large)
            self.assertEqual(await transport.recv(), large)
            self.assertEqual(received, [small, large])
        finally:
            await transport.close()
            server.close()
            await server.wait_closed()

    def test_session_state_counters_and_sqlite_persistence(self) -> None:
        key = AuthKey(os.urandom(256))
        state = MTProtoSessionState(dc_id=4, host="149.154.167.91", auth_key=key, server_salt=123456789)

        # msg_id must be strictly increasing and divisible by 4
        ids = [state.next_msg_id() for _ in range(5)]
        for i, mid in enumerate(ids):
            self.assertEqual(mid % 4, 0)
            if i > 0:
                self.assertGreater(mid, ids[i - 1])

        # seq_no rules: content-related is odd and increments; non-content is even and does not
        self.assertEqual(state.next_seq_no(False), 0)
        self.assertEqual(state.next_seq_no(True), 1)
        self.assertEqual(state.next_seq_no(False), 2)
        self.assertEqual(state.next_seq_no(True), 3)
        self.assertEqual(state.next_seq_no(True), 5)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "session.sqlite"
            state.save_sqlite(db)
            loaded = MTProtoSessionState.load_sqlite(db)
            assert loaded is not None
            self.assertEqual(loaded.dc_id, 4)
            self.assertEqual(loaded.host, "149.154.167.91")
            self.assertEqual(loaded.server_salt, 123456789)
            assert loaded.auth_key is not None
            self.assertEqual(loaded.auth_key.key, key.key)

    def test_wire_encrypted_container_bad_salt_and_rpc(self) -> None:
        key = AuthKey(os.urandom(256))
        state = MTProtoSessionState(auth_key=key, server_salt=999)
        wire = MTProtoWire(state)

        # Pack and simulate server response with gzip_packed rpc_result
        req_id, enc_pkt = wire.pack_encrypted(b"\x11\x22\x33\x44", content_related=True)
        self.assertGreater(req_id, 0)

        # Simulate server sending encrypted gzip_packed rpc_result back to client
        rpc_inner = TLWriter()
        rpc_inner.write_uint(RPC_RESULT_ID)
        rpc_inner.write_long(req_id)
        rpc_inner.write_raw(b"OK_DATA!")
        gz_body = pack_gzip(rpc_inner.to_bytes())

        srv_inner = TLWriter()
        srv_inner.write_long(state.server_salt)
        srv_inner.write_raw(struct.pack("<Q", state.session_id))
        srv_inner.write_long(req_id + 1)
        srv_inner.write_int(1)
        srv_inner.write_int(len(gz_body))
        srv_inner.write_raw(gz_body)
        srv_pkt = key.encrypt_packet(srv_inner.to_bytes(), from_client=False)

        _mid, _seq, unpacked_body = wire.unpack_encrypted(srv_pkt, from_client=False)
        got_req_id, result_bytes = wire.unpack_rpc_result(unpacked_body)
        self.assertEqual(got_req_id, req_id)
        self.assertEqual(result_bytes, b"OK_DATA!")

        # Test rpc_error raises MTProtoRPCError
        err_w = TLWriter()
        err_w.write_uint(RPC_RESULT_ID)
        err_w.write_long(req_id)
        err_w.write_uint(RPC_ERROR_ID)
        err_w.write_int(420)
        err_w.write_string("FLOOD_WAIT_15")
        with self.assertRaises(MTProtoRPCError) as ctx:
            wire.unpack_rpc_result(err_w.to_bytes())
        self.assertEqual(ctx.exception.code, 420)
        self.assertEqual(ctx.exception.message, "FLOOD_WAIT_15")

        # Test bad_server_salt updates state.server_salt
        bs_w = TLWriter()
        bs_w.write_uint(BAD_SERVER_SALT_ID)
        bs_w.write_long(req_id)
        bs_w.write_int(1)
        bs_w.write_int(48)
        bs_w.write_long(777888999)
        bad_id, err_code, new_salt = wire.handle_bad_server_salt(bs_w.to_bytes())
        self.assertEqual((bad_id, err_code, new_salt), (req_id, 48, 777888999))
        self.assertEqual(state.server_salt, 777888999)

        # Test msg_container roundtrip
        container = wire.pack_container([(100, 1, b"AAAA"), (104, 3, b"BBBB")])
        items = wire.unpack_container(container)
        self.assertEqual(items, [(100, 1, b"AAAA"), (104, 3, b"BBBB")])
