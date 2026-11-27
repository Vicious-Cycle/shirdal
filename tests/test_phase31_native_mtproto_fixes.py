"""Regression tests for the NativeMTProtoAdapter fixes (schema runtime, updates, resend, migrate)."""

import asyncio
import os
import struct
import unittest

from shirdal import EventType, NativeMTProtoAdapter
from shirdal.core.native_mtproto_adapter import marked_id, parse_html, split_marked_id
from shirdal.mtproto import (
    BAD_SERVER_SALT_ID,
    MSGS_ACK_ID,
    RPC_ERROR_ID,
    RPC_RESULT_ID,
    AuthKey,
    TLReader,
    TLWriter,
)
from shirdal.mtproto.srp import compute_check
from shirdal.mtproto.tl_runtime import api_layer, deserialize, get_schema, serialize

S = get_schema()


def _frame(payload: bytes) -> bytes:
    words = len(payload) // 4
    return (bytes([words]) if words < 127 else b"\x7f" + words.to_bytes(3, "little")) + payload


class FakeServer:
    """Minimal encrypted MTProto server; `handler(method_body) -> list[bytes]` responses."""

    def __init__(self, auth_key: AuthKey, salt: int) -> None:
        self.auth_key = auth_key
        self.salt = salt
        self.requests: list[bytes] = []
        self.handler = None
        self.writer = None
        self.sess = 0
        self._srv_msg = 1 << 32

    def _send(self, body: bytes, seq: int = 1) -> None:
        self._srv_msg += 4
        w = TLWriter()
        w.write_long(self.salt)
        w.write_raw(struct.pack("<Q", self.sess))
        w.write_long(self._srv_msg)
        w.write_int(seq)
        w.write_int(len(body))
        w.write_raw(body)
        self.writer.write(_frame(self.auth_key.encrypt_packet(w.to_bytes(), from_client=False)))

    def push(self, body: bytes) -> None:
        self._send(body)

    async def serve(self, reader, writer) -> None:
        self.writer = writer
        await reader.readexactly(1)
        try:
            while True:
                first = (await reader.readexactly(1))[0]
                words = first if first < 127 else int.from_bytes(await reader.readexactly(3), "little")
                pkt = await reader.readexactly(words * 4)
                r = TLReader(self.auth_key.decrypt_packet(pkt, from_client=True))
                pkt_salt = r.read_long()
                self.sess = struct.unpack("<Q", r.read_raw(8))[0]
                msg_id = r.read_long()
                r.read_int()
                body = r.read_raw(r.read_int())
                if struct.unpack_from("<I", body, 0)[0] == MSGS_ACK_ID:
                    continue
                self.requests.append(body)
                for resp in self.handler(msg_id, body, pkt_salt):
                    self._send(resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()


def rpc_result(req_id: int, inner: bytes) -> bytes:
    w = TLWriter()
    w.write_uint(RPC_RESULT_ID)
    w.write_long(req_id)
    w.write_raw(inner)
    return w.to_bytes()


def rpc_error(req_id: int, code: int, msg: str) -> bytes:
    w = TLWriter()
    w.write_uint(RPC_ERROR_ID)
    w.write_int(code)
    w.write_string(msg)
    return rpc_result(req_id, w.to_bytes())


def strip_init(body: bytes) -> bytes:
    """Remove invokeWithLayer(initConnection(...)) wrapper if present."""
    r = TLReader(body)
    if r.read_uint() != S.funcs["invokeWithLayer"].id:
        return body
    r.read_int()
    assert r.read_uint() == S.funcs["initConnection"].id
    r.read_uint()  # flags
    r.read_int()
    for _ in range(6):
        r.read_string()
    return r.read_raw(r.remaining())


def method_name(body: bytes) -> str:
    cid = struct.unpack_from("<I", strip_init(body), 0)[0]
    return S.by_id[cid].name


class TestSchemaRuntime(unittest.TestCase):
    def test_layer_and_ids_match_schema(self) -> None:
        self.assertGreaterEqual(api_layer(), 200)
        self.assertEqual(S.funcs["messages.sendMessage"].id, 0x545CD15A)

    def test_roundtrip_message_with_flags(self) -> None:
        raw = serialize(
            "message",
            out=True,
            id=5,
            from_id={"_": "peerUser", "user_id": 1},
            peer_id={"_": "peerChannel", "channel_id": 99},
            date=1,
            message="سلام",
            entities=[{"_": "messageEntityBold", "offset": 0, "length": 4}],
        )
        obj = deserialize(raw)
        self.assertEqual(obj["message"], "سلام")
        self.assertTrue(obj["out"])
        self.assertEqual(obj["peer_id"]["channel_id"], 99)
        self.assertEqual(obj["entities"][0]["_"], "messageEntityBold")

    def test_marked_ids(self) -> None:
        self.assertEqual(marked_id({"_": "peerChat", "chat_id": 5}), -5)
        self.assertEqual(marked_id({"_": "peerChannel", "channel_id": 5}), -1000000000005)
        self.assertEqual(split_marked_id(-1000000000005), ("channel", 5))
        self.assertEqual(split_marked_id(-5), ("chat", 5))

    def test_html_entities(self) -> None:
        text, ents = parse_html('<b>Hi</b> <a href="https://x.y">x</a><br><blockquote>q</blockquote>')
        self.assertEqual(text, "Hi x\nq")
        self.assertEqual([e["_"] for e in ents], ["messageEntityBold", "messageEntityTextUrl", "messageEntityBlockquote"])

    def test_srp_shape(self) -> None:
        p = (1 << 2047) + 1155  # not a safe prime, only shape-tested here
        acc = {
            "current_algo": {
                "_": "passwordKdfAlgoSHA256SHA256PBKDF2HMACSHA512iter100000SHA256ModPow",
                "salt1": b"a" * 8,
                "salt2": b"b" * 16,
                "g": 3,
                "p": p.to_bytes(256, "big"),
            },
            "srp_B": (12345).to_bytes(256, "big"),
            "srp_id": 77,
        }
        chk = compute_check(acc, "pw")
        self.assertEqual(chk["srp_id"], 77)
        self.assertEqual(len(chk["A"]), 256)
        self.assertEqual(len(chk["M1"]), 32)


class TestNativeAdapterFixes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.auth_key = AuthKey(os.urandom(256))
        self.srv = FakeServer(self.auth_key, 42)
        self.server = await asyncio.start_server(self.srv.serve, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.adapter = NativeMTProtoAdapter(
            1, "h", host="127.0.0.1", port=port, auth_key=self.auth_key, server_salt=42, rpc_timeout=3
        )

    async def asyncTearDown(self) -> None:
        await self.adapter.disconnect()
        self.server.close()
        await self.server.wait_closed()

    async def test_first_request_wrapped_and_real_message_id(self) -> None:
        def handler(req_id, body, _salt):
            self.assertEqual(struct.unpack_from("<I", body, 0)[0], S.funcs["invokeWithLayer"].id)
            return [rpc_result(req_id, serialize("updateShortSentMessage", id=4242, pts=10, pts_count=1, date=1))]

        self.srv.handler = handler
        await self.adapter.connect()
        msg = await self.adapter.send_message("me", "<b>hi</b>")
        self.assertEqual(msg.id, 4242)
        self.assertEqual(msg.text, "hi")
        self.assertEqual(method_name(self.srv.requests[0]), "messages.sendMessage")

    async def test_bad_server_salt_resends(self) -> None:
        def handler(req_id, body, salt):
            if salt != 777:
                w = TLWriter()
                w.write_uint(BAD_SERVER_SALT_ID)
                w.write_long(req_id)
                w.write_int(0)
                w.write_int(48)
                w.write_long(777)
                return [w.to_bytes()]
            return [rpc_result(req_id, serialize("boolTrue"))]

        self.srv.handler = handler

        async def _no_sync() -> None:  # background updates.getState would add extra requests
            return None

        self.adapter._initial_sync = _no_sync
        await self.adapter.connect()
        self.assertIs(await self.adapter.call("help.getConfig"), True)
        self.assertEqual(len(self.srv.requests), 2)

    async def test_channel_and_group_updates_parsed(self) -> None:
        self.srv.handler = lambda req_id, *_: [rpc_result(req_id, serialize("boolTrue"))]
        await self.adapter.connect()
        await self.adapter.call("help.getConfig")  # server learns our session id
        upd = serialize(
            "updates",
            updates=[
                {
                    "_": "updateNewChannelMessage",
                    "message": {
                        "_": "message",
                        "id": 7,
                        "from_id": {"_": "peerUser", "user_id": 11},
                        "peer_id": {"_": "peerChannel", "channel_id": 500},
                        "date": 1,
                        "message": ".ping",
                    },
                    "pts": 3,
                    "pts_count": 1,
                }
            ],
            users=[{"_": "user", "id": 11, "access_hash": 99, "first_name": "Ali", "username": "ali"}],
            chats=[{"_": "channel", "megagroup": True, "id": 500, "access_hash": 55, "title": "G", "photo": {"_": "chatPhotoEmpty"}, "date": 1}],
            date=1,
            seq=0,
        )
        self.srv.push(upd)
        self.srv.push(
            serialize("updateShortChatMessage", id=8, from_id=11, chat_id=600, message="hey", pts=1, pts_count=1, date=1)
        )
        await self.srv.writer.drain()
        it = self.adapter.listen().__aiter__()
        ev1 = await asyncio.wait_for(it.__anext__(), 2)
        ev2 = await asyncio.wait_for(it.__anext__(), 2)
        self.assertEqual(ev1.type, EventType.NEW_MESSAGE)
        self.assertEqual(ev1.message.chat.id, -1000000000500)
        self.assertEqual(ev1.message.chat.type, "supergroup")
        self.assertEqual(ev1.message.sender.id, 11)
        self.assertEqual(ev1.message.text, ".ping")
        self.assertEqual(ev2.message.chat.id, -600)
        self.assertEqual(ev2.message.chat.type, "group")
        rec = self.adapter.peers.get("channel", 500)
        self.assertEqual(rec.access_hash, 55)
        self.assertEqual(self.adapter.peers.get_by_username("ali").access_hash, 99)

        # Reply to the group goes to inputPeerChat, not a user (old bug #1)
        self.srv.handler = lambda req_id, body, _s: [
            rpc_result(req_id, serialize("updateShortSentMessage", id=9, pts=2, pts_count=1, date=1))
        ]
        await self.adapter.send_message(ev2.message.chat.id, "ok", reply_to=8)
        sent = deserialize(strip_init(self.srv.requests[-1]))
        self.assertEqual(sent["peer"], {"_": "inputPeerChat", "chat_id": 600})
        self.assertEqual(sent["reply_to"]["reply_to_msg_id"], 8)

    async def test_phone_migrate_switches_dc(self) -> None:
        self.adapter._custom_host = False  # allow migration in test
        switched: list[int] = []

        async def fake_switch(dc: int) -> None:
            switched.append(dc)

        self.adapter._switch_dc = fake_switch  # type: ignore[assignment]
        calls = {"n": 0}

        def handler(req_id, body, _s):
            calls["n"] += 1
            if calls["n"] == 1:
                return [rpc_error(req_id, 303, "PHONE_MIGRATE_4")]
            return [rpc_result(req_id, serialize("boolTrue"))]

        self.srv.handler = handler
        await self.adapter.connect()
        self.assertIs(await self.adapter.call("help.getConfig"), True)
        self.assertEqual(switched, [4])


if __name__ == "__main__":
    unittest.main()
