"""MTProto 2.0 session state, SQLite persistence, and encrypted wire framing."""

from __future__ import annotations

import os
import sqlite3
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from shirdal._fs import secure_file
from shirdal.mtproto.crypto import AuthKey, MTProtoCryptoError
from shirdal.mtproto.tl_codec import GZIP_PACKED_ID, TLReader, TLWriter, unpack_gzip

MSG_CONTAINER_ID = 0x73F1F8DC
MSGS_ACK_ID = 0x62D6B459
BAD_SERVER_SALT_ID = 0xEDAB447B
BAD_MSG_NOTIFICATION_ID = 0xA7EFF811
RPC_RESULT_ID = 0xF35C6D01
RPC_ERROR_ID = 0x2144CA19


class MTProtoRPCError(Exception):
    """Raised when Telegram returns rpc_error#2144ca19."""

    def __init__(self, code: int, message: str) -> None:
        self.code = int(code)
        self.message = message
        super().__init__(f"[{self.code}] {self.message}")


@dataclass(slots=True)
class MTProtoSessionState:
    """In-memory and SQLite-backed MTProto 2.0 session state."""

    dc_id: int = 2
    host: str = "149.154.167.50"
    port: int = 443
    auth_key: AuthKey | None = None
    server_salt: int = 0
    layer: int = 195
    session_id: int = field(default_factory=lambda: struct.unpack("<Q", os.urandom(8))[0])
    time_offset: int = 0
    _last_msg_id: int = 0
    _seq_no: int = 0

    def next_msg_id(self) -> int:
        now = time.time() + self.time_offset
        msg_id = int(now * (1 << 32)) & ~3
        if msg_id <= self._last_msg_id:
            msg_id = self._last_msg_id + 4
        self._last_msg_id = msg_id
        return msg_id

    def next_seq_no(self, content_related: bool = True) -> int:
        seq = self._seq_no * 2 + (1 if content_related else 0)
        if content_related:
            self._seq_no += 1
        return seq

    def reset_runtime_counters(self) -> None:
        self.session_id = struct.unpack("<Q", os.urandom(8))[0]
        self._last_msg_id = 0
        self._seq_no = 0

    def sync_time_offset(self, server_msg_id: int) -> int:
        """Synchronize local time_offset from a server msg_id."""
        server_sec = server_msg_id >> 32
        local_sec = int(time.time())
        self.time_offset = server_sec - local_sec
        return self.time_offset

    def save_sqlite(self, db_path: str | Path) -> None:
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(p) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mtproto_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    dc_id INTEGER NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    auth_key BLOB,
                    server_salt INTEGER NOT NULL,
                    layer INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO mtproto_session (id, dc_id, host, port, auth_key, server_salt, layer)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    dc_id = excluded.dc_id,
                    host = excluded.host,
                    port = excluded.port,
                    auth_key = excluded.auth_key,
                    server_salt = excluded.server_salt,
                    layer = excluded.layer
                """,
                (
                    self.dc_id,
                    self.host,
                    self.port,
                    self.auth_key.key if self.auth_key else None,
                    self.server_salt,
                    self.layer,
                ),
            )
            conn.commit()
        secure_file(p)

    @classmethod
    def load_sqlite(cls, db_path: str | Path) -> MTProtoSessionState | None:
        p = Path(db_path)
        if not p.exists():
            return None
        with sqlite3.connect(p) as conn:
            row = conn.execute(
                "SELECT dc_id, host, port, auth_key, server_salt, layer FROM mtproto_session WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        dc_id, host, port, key_blob, server_salt, layer = row
        auth_key = AuthKey(bytes(key_blob)) if key_blob is not None else None
        return cls(
            dc_id=int(dc_id),
            host=str(host),
            port=int(port),
            auth_key=auth_key,
            server_salt=int(server_salt),
            layer=int(layer),
        )


class MTProtoWire:
    """Packs and unpacks encrypted/unencrypted MTProto 2.0 wire messages."""

    def __init__(self, state: MTProtoSessionState) -> None:
        self.state = state

    def pack_unencrypted(self, body: bytes) -> bytes:
        msg_id = self.state.next_msg_id()
        w = TLWriter()
        w.write_long(0)  # auth_key_id = 0
        w.write_long(msg_id)
        w.write_int(len(body))
        w.write_raw(body)
        return w.to_bytes()

    def unpack_unencrypted(self, packet: bytes) -> tuple[int, bytes]:
        r = TLReader(packet)
        key_id = r.read_long()
        if key_id != 0:
            raise MTProtoCryptoError(f"Expected unencrypted auth_key_id=0, got {key_id}")
        msg_id = r.read_long()
        msg_len = r.read_int()
        return msg_id, r.read_raw(msg_len)

    def pack_encrypted(self, body: bytes, *, content_related: bool = True) -> tuple[int, bytes]:
        if self.state.auth_key is None:
            raise MTProtoCryptoError("Cannot encrypt packet without AuthKey.")
        msg_id = self.state.next_msg_id()
        seq_no = self.state.next_seq_no(content_related)

        inner = TLWriter()
        inner.write_long(self.state.server_salt)
        inner.write_raw(struct.pack("<Q", self.state.session_id))
        inner.write_long(msg_id)
        inner.write_int(seq_no)
        inner.write_int(len(body))
        inner.write_raw(body)
        return msg_id, self.state.auth_key.encrypt_packet(inner.to_bytes(), from_client=True)

    def unpack_encrypted(self, packet: bytes, *, from_client: bool = False) -> tuple[int, int, bytes]:
        if self.state.auth_key is None:
            raise MTProtoCryptoError("Cannot decrypt packet without AuthKey.")
        padded = self.state.auth_key.decrypt_packet(packet, from_client=from_client)
        r = TLReader(padded)
        _salt = r.read_long()
        session_id = struct.unpack("<Q", r.read_raw(8))[0]
        if session_id != self.state.session_id:
            raise MTProtoCryptoError("Session ID mismatch in decrypted packet.")
        msg_id = r.read_long()
        seq_no = r.read_int()
        msg_len = r.read_int()
        body = r.read_raw(msg_len)
        if len(body) >= 4 and struct.unpack_from("<I", body, 0)[0] == GZIP_PACKED_ID:
            body = unpack_gzip(TLReader(body))
        return msg_id, seq_no, body

    def pack_acks(self, msg_ids: list[int]) -> bytes:
        w = TLWriter()
        w.write_uint(MSGS_ACK_ID)
        w.write_vector(msg_ids, TLWriter.write_long)
        return w.to_bytes()

    def pack_container(self, items: list[tuple[int, int, bytes]]) -> bytes:
        """Pack [(msg_id, seq_no, body), ...] into msg_container#73f1f8dc."""
        w = TLWriter()
        w.write_uint(MSG_CONTAINER_ID)
        w.write_int(len(items))
        for msg_id, seq_no, body in items:
            w.write_long(msg_id)
            w.write_int(seq_no)
            w.write_int(len(body))
            w.write_raw(body)
        return w.to_bytes()

    def unpack_container(self, body: bytes) -> list[tuple[int, int, bytes]]:
        r = TLReader(body)
        cid = r.read_uint()
        if cid != MSG_CONTAINER_ID:
            raise MTProtoCryptoError(f"Expected msg_container, got 0x{cid:08x}")
        count = r.read_int()
        out: list[tuple[int, int, bytes]] = []
        for _ in range(count):
            msg_id = r.read_long()
            seq_no = r.read_int()
            msg_len = r.read_int()
            item_body = r.read_raw(msg_len)
            if len(item_body) >= 4 and struct.unpack_from("<I", item_body, 0)[0] == GZIP_PACKED_ID:
                item_body = unpack_gzip(TLReader(item_body))
            out.append((msg_id, seq_no, item_body))
        return out

    def handle_bad_server_salt(self, body: bytes) -> tuple[int, int, int]:
        """Parse bad_server_salt#edab447b, update state.server_salt, and return (bad_msg_id, error_code, new_salt)."""
        r = TLReader(body)
        cid = r.read_uint()
        if cid != BAD_SERVER_SALT_ID:
            raise MTProtoCryptoError(f"Expected bad_server_salt, got 0x{cid:08x}")
        bad_msg_id = r.read_long()
        _bad_seq = r.read_int()
        error_code = r.read_int()
        new_salt = r.read_long()
        self.state.server_salt = new_salt
        return bad_msg_id, error_code, new_salt

    def handle_bad_msg_notification(self, body: bytes) -> tuple[int, int, int]:
        """Parse bad_msg_notification#a7eff811 and return (bad_msg_id, bad_seqno, error_code)."""
        r = TLReader(body)
        cid = r.read_uint()
        if cid != BAD_MSG_NOTIFICATION_ID:
            raise MTProtoCryptoError(f"Expected bad_msg_notification, got 0x{cid:08x}")
        bad_msg_id = r.read_long()
        bad_seqno = r.read_int()
        error_code = r.read_int()
        if error_code in (16, 17):
            # msg_id too low / too high: reset _last_msg_id
            self.state._last_msg_id = 0
        return bad_msg_id, bad_seqno, error_code

    def handle_new_session_created(self, body: bytes) -> tuple[int, int, int]:
        """Parse new_session_created#9ec20908, update server_salt, return (first_msg_id, unique_id, server_salt)."""
        r = TLReader(body)
        cid = r.read_uint()
        if cid != 0x9EC20908:
            raise MTProtoCryptoError(f"Expected new_session_created, got 0x{cid:08x}")
        first_msg_id = r.read_long()
        unique_id = r.read_long()
        server_salt = r.read_long()
        self.state.server_salt = server_salt
        return first_msg_id, unique_id, server_salt

    @staticmethod
    def handle_pong(body: bytes) -> tuple[int, int]:
        """Parse pong#347773c5 and return (msg_id, ping_id)."""
        r = TLReader(body)
        cid = r.read_uint()
        if cid != 0x347773C5:
            raise MTProtoCryptoError(f"Expected pong, got 0x{cid:08x}")
        msg_id = r.read_long()
        ping_id = r.read_long()
        return msg_id, ping_id

    @staticmethod
    def unpack_rpc_result(body: bytes) -> tuple[int, bytes]:
        """Unpack rpc_result#f35c6d01; raises MTProtoRPCError if inner result is rpc_error."""
        r = TLReader(body)
        cid = r.read_uint()
        if cid != RPC_RESULT_ID:
            raise MTProtoCryptoError(f"Expected rpc_result, got 0x{cid:08x}")
        req_msg_id = r.read_long()
        inner = r.read_raw(r.remaining())
        if len(inner) >= 4 and struct.unpack_from("<I", inner, 0)[0] == GZIP_PACKED_ID:
            inner = unpack_gzip(TLReader(inner))
        if len(inner) >= 4 and struct.unpack_from("<I", inner, 0)[0] == RPC_ERROR_ID:
            er = TLReader(inner)
            er.read_uint()
            err_code = er.read_int()
            err_msg = er.read_string()
            raise MTProtoRPCError(err_code, err_msg)
        return req_msg_id, inner
