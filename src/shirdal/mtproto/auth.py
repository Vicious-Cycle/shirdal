"""MTProto 2.0 Diffie-Hellman AuthKey handshake state machine."""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

from shirdal.mtproto.crypto import (
    AuthKey,
    MTProtoCryptoError,
    aes_ige_decrypt,
    aes_ige_encrypt,
    factorize_pq,
    rsa_encrypt_raw,
    rsa_fingerprint,
)
from shirdal.mtproto.tl_codec import TLReader, TLWriter

REQ_PQ_MULTI_ID = 0xBE7E8EF1
RES_PQ_ID = 0x05162463
P_Q_INNER_DATA_ID = 0x83C95AEC
REQ_DH_PARAMS_ID = 0xD712E4BE
SERVER_DH_PARAMS_OK_ID = 0xD0E8075C
SERVER_DH_INNER_DATA_ID = 0xB5890DBA
CLIENT_DH_INNER_DATA_ID = 0x6643B654
SET_CLIENT_DH_PARAMS_ID = 0xF5045F1F
DH_GEN_OK_ID = 0x3BCBF734


@dataclass(slots=True, frozen=True)
class RSAPublicKey:
    n: int
    e: int

    @property
    def fingerprint(self) -> int:
        return rsa_fingerprint(self.n, self.e)


def derive_tmp_aes_key_iv(new_nonce: bytes, server_nonce: bytes) -> tuple[bytes, bytes]:
    """Derive temporary AES-256-IGE key and IV for DH parameter exchange."""
    h1 = hashlib.sha1(new_nonce + server_nonce).digest()
    h2 = hashlib.sha1(server_nonce + new_nonce).digest()
    h3 = hashlib.sha1(new_nonce + new_nonce).digest()
    tmp_aes_key = h1 + h2[:12]
    tmp_aes_iv = h2[12:20] + h3 + new_nonce[:4]
    return tmp_aes_key, tmp_aes_iv


class HandshakeSession:
    """Stateless-transport 3-step MTProto 2.0 Diffie-Hellman key exchange."""

    def __init__(self, rsa_keys: list[RSAPublicKey]) -> None:
        self.rsa_keys = {k.fingerprint: k for k in rsa_keys}
        self.nonce: bytes = b""
        self.server_nonce: bytes = b""
        self.new_nonce: bytes = b""
        self._b: int = 0
        self._dh_prime: int = 0
        self._g_a: int = 0
        self._auth_key_bytes: bytes = b""

    def step1_req_pq_multi(self, nonce: bytes | None = None) -> bytes:
        self.nonce = nonce if nonce is not None else os.urandom(16)
        if len(self.nonce) != 16:
            raise MTProtoCryptoError("nonce must be 16 bytes")
        w = TLWriter()
        w.write_uint(REQ_PQ_MULTI_ID)
        w.write_int128(self.nonce)
        return w.to_bytes()

    def step2_handle_res_pq(self, payload: bytes, new_nonce: bytes | None = None) -> bytes:
        r = TLReader(payload)
        cid = r.read_uint()
        if cid != RES_PQ_ID:
            raise MTProtoCryptoError(f"Expected resPQ (0x{RES_PQ_ID:08x}), got 0x{cid:08x}")

        srv_client_nonce = r.read_int128_bytes()
        if srv_client_nonce != self.nonce:
            raise MTProtoCryptoError("resPQ nonce mismatch")
        self.server_nonce = r.read_int128_bytes()
        pq_bytes = r.read_bytes()
        pq = int.from_bytes(pq_bytes, "big")
        fingerprints = r.read_vector(TLReader.read_long)

        selected_key: RSAPublicKey | None = None
        for fp in fingerprints:
            if fp in self.rsa_keys:
                selected_key = self.rsa_keys[fp]
                break
        if selected_key is None:
            raise MTProtoCryptoError("No matching RSA public key fingerprint found")

        p, q = factorize_pq(pq)
        p_bytes = p.to_bytes((p.bit_length() + 7) // 8, "big")
        q_bytes = q.to_bytes((q.bit_length() + 7) // 8, "big")

        self.new_nonce = new_nonce if new_nonce is not None else os.urandom(32)
        if len(self.new_nonce) != 32:
            raise MTProtoCryptoError("new_nonce must be 32 bytes")

        inner = TLWriter()
        inner.write_uint(P_Q_INNER_DATA_ID)
        inner.write_bytes(pq_bytes)
        inner.write_bytes(p_bytes)
        inner.write_bytes(q_bytes)
        inner.write_int128(self.nonce)
        inner.write_int128(self.server_nonce)
        inner.write_int256(self.new_nonce)
        inner_bytes = inner.to_bytes()

        data_with_hash = hashlib.sha1(inner_bytes).digest() + inner_bytes
        encrypted_data = rsa_encrypt_raw(data_with_hash, selected_key.n, selected_key.e)

        req = TLWriter()
        req.write_uint(REQ_DH_PARAMS_ID)
        req.write_int128(self.nonce)
        req.write_int128(self.server_nonce)
        req.write_bytes(p_bytes)
        req.write_bytes(q_bytes)
        req.write_long(selected_key.fingerprint)
        req.write_bytes(encrypted_data)
        return req.to_bytes()

    def step3_handle_server_dh_params(self, payload: bytes, b_bytes: bytes | None = None) -> bytes:
        r = TLReader(payload)
        cid = r.read_uint()
        if cid != SERVER_DH_PARAMS_OK_ID:
            raise MTProtoCryptoError(
                f"Expected server_DH_params_ok (0x{SERVER_DH_PARAMS_OK_ID:08x}), got 0x{cid:08x}"
            )
        if r.read_int128_bytes() != self.nonce:
            raise MTProtoCryptoError("server_DH_params nonce mismatch")
        if r.read_int128_bytes() != self.server_nonce:
            raise MTProtoCryptoError("server_DH_params server_nonce mismatch")
        encrypted_answer = r.read_bytes()

        tmp_key, tmp_iv = derive_tmp_aes_key_iv(self.new_nonce, self.server_nonce)
        answer_with_hash = aes_ige_decrypt(encrypted_answer, tmp_key, tmp_iv)
        digest = answer_with_hash[:20]
        answer_body = answer_with_hash[20:]

        # Parse server_DH_inner_data to determine exact TL length for SHA-1 verification
        ir = TLReader(answer_body)
        icid = ir.read_uint()
        if icid != SERVER_DH_INNER_DATA_ID:
            raise MTProtoCryptoError(f"Expected server_DH_inner_data, got 0x{icid:08x}")
        if ir.read_int128_bytes() != self.nonce:
            raise MTProtoCryptoError("server_DH_inner_data nonce mismatch")
        if ir.read_int128_bytes() != self.server_nonce:
            raise MTProtoCryptoError("server_DH_inner_data server_nonce mismatch")
        g = ir.read_int()
        dh_prime_bytes = ir.read_bytes()
        g_a_bytes = ir.read_bytes()
        _server_time = ir.read_int()

        exact_inner = answer_body[: ir.pos]
        if hashlib.sha1(exact_inner).digest() != digest:
            raise MTProtoCryptoError("server_DH_inner_data SHA-1 verification failed")

        dh_prime = int.from_bytes(dh_prime_bytes, "big")
        g_a = int.from_bytes(g_a_bytes, "big")
        if not (1 < g_a < dh_prime - 1):
            raise MTProtoCryptoError("Invalid g_a from server")

        b_raw = b_bytes if b_bytes is not None else os.urandom(256)
        b = int.from_bytes(b_raw, "big")
        g_b = pow(g, b, dh_prime)
        if not (1 < g_b < dh_prime - 1):
            raise MTProtoCryptoError("Invalid g_b")

        auth_key_int = pow(g_a, b, dh_prime)
        self._auth_key_bytes = auth_key_int.to_bytes(256, "big")

        g_b_bytes = g_b.to_bytes((g_b.bit_length() + 7) // 8, "big")
        c_inner = TLWriter()
        c_inner.write_uint(CLIENT_DH_INNER_DATA_ID)
        c_inner.write_int128(self.nonce)
        c_inner.write_int128(self.server_nonce)
        c_inner.write_long(0)  # retry_id
        c_inner.write_bytes(g_b_bytes)
        c_inner_bytes = c_inner.to_bytes()

        c_with_hash = hashlib.sha1(c_inner_bytes).digest() + c_inner_bytes
        pad = (-len(c_with_hash)) % 16
        if pad:
            c_with_hash += os.urandom(pad)
        encrypted_dh = aes_ige_encrypt(c_with_hash, tmp_key, tmp_iv)

        req = TLWriter()
        req.write_uint(SET_CLIENT_DH_PARAMS_ID)
        req.write_int128(self.nonce)
        req.write_int128(self.server_nonce)
        req.write_bytes(encrypted_dh)
        return req.to_bytes()

    def step4_handle_dh_gen(self, payload: bytes) -> tuple[AuthKey, int]:
        r = TLReader(payload)
        cid = r.read_uint()
        if cid != DH_GEN_OK_ID:
            raise MTProtoCryptoError(f"Expected dh_gen_ok (0x{DH_GEN_OK_ID:08x}), got 0x{cid:08x}")
        if r.read_int128_bytes() != self.nonce:
            raise MTProtoCryptoError("dh_gen_ok nonce mismatch")
        if r.read_int128_bytes() != self.server_nonce:
            raise MTProtoCryptoError("dh_gen_ok server_nonce mismatch")
        new_nonce_hash1 = r.read_int128_bytes()

        auth_key = AuthKey(self._auth_key_bytes)
        expected_hash1 = hashlib.sha1(self.new_nonce + b"\x01" + auth_key.aux_hash).digest()[4:20]
        if new_nonce_hash1 != expected_hash1:
            raise MTProtoCryptoError("dh_gen_ok new_nonce_hash1 verification failed")

        salt_bytes = bytes(a ^ b for a, b in zip(self.new_nonce[:8], self.server_nonce[:8]))
        server_salt = struct.unpack("<q", salt_bytes)[0]
        return auth_key, server_salt
