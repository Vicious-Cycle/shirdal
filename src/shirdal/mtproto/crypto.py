"""MTProto 2.0 cryptographic primitives (AES-256-IGE, KDF, AuthKey, RSA, Pollard's rho)."""

from __future__ import annotations

import hashlib
import math
import os
import random
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

try:
    import shircrypt as _shircrypt
except ImportError:
    _shircrypt = None

from shirdal.mtproto.tl_codec import TLWriter


def crypto_backend() -> str:
    """Return a human-readable name of the active AES-IGE backend."""
    if _shircrypt is not None and _shircrypt.BACKEND == "rust":
        return f"shircrypt-rust (v{getattr(_shircrypt, '__version__', '?')})"
    return "cryptography (python fallback)"


class MTProtoCryptoError(ValueError):
    """Raised on MTProto 2.0 encryption, decryption, or integrity verification failure."""


def _xor16(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(16, "big")


def aes_ige_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt data using AES-256-IGE (Infinite Garble Extension)."""
    if _shircrypt is not None and _shircrypt.BACKEND == "rust":
        try:
            return _shircrypt.ige256_encrypt(data, key, iv)
        except ValueError as exc:
            raise MTProtoCryptoError(str(exc)) from exc
    if len(key) != 32:
        raise MTProtoCryptoError(f"AES-256-IGE key must be 32 bytes, got {len(key)}")
    if len(iv) != 32:
        raise MTProtoCryptoError(f"AES-256-IGE IV must be 32 bytes, got {len(iv)}")
    if len(data) % 16 != 0:
        raise MTProtoCryptoError(f"AES-256-IGE plaintext length must be a multiple of 16, got {len(data)}")

    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    iv_c = iv[:16]
    iv_p = iv[16:]
    out = bytearray(len(data))

    for offset in range(0, len(data), 16):
        plain_block = data[offset : offset + 16]
        xored = _xor16(plain_block, iv_c)
        enc = encryptor.update(xored)
        cipher_block = _xor16(enc, iv_p)
        out[offset : offset + 16] = cipher_block
        iv_c = cipher_block
        iv_p = plain_block

    encryptor.finalize()
    return bytes(out)


def aes_ige_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt data using AES-256-IGE (Infinite Garble Extension)."""
    if _shircrypt is not None and _shircrypt.BACKEND == "rust":
        try:
            return _shircrypt.ige256_decrypt(data, key, iv)
        except ValueError as exc:
            raise MTProtoCryptoError(str(exc)) from exc
    if len(key) != 32:
        raise MTProtoCryptoError(f"AES-256-IGE key must be 32 bytes, got {len(key)}")
    if len(iv) != 32:
        raise MTProtoCryptoError(f"AES-256-IGE IV must be 32 bytes, got {len(iv)}")
    if len(data) % 16 != 0:
        raise MTProtoCryptoError(f"AES-256-IGE ciphertext length must be a multiple of 16, got {len(data)}")

    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    iv_c = iv[:16]
    iv_p = iv[16:]
    out = bytearray(len(data))

    for offset in range(0, len(data), 16):
        cipher_block = data[offset : offset + 16]
        xored = _xor16(cipher_block, iv_p)
        dec = decryptor.update(xored)
        plain_block = _xor16(dec, iv_c)
        out[offset : offset + 16] = plain_block
        iv_c = cipher_block
        iv_p = plain_block

    decryptor.finalize()
    return bytes(out)


def compute_msg_key(auth_key: bytes, padded_plaintext: bytes, *, from_client: bool = True) -> bytes:
    """Compute 16-byte MTProto 2.0 msg_key."""
    if len(auth_key) != 256:
        raise MTProtoCryptoError(f"auth_key must be 256 bytes, got {len(auth_key)}")
    x = 0 if from_client else 8
    msg_key_large = hashlib.sha256(auth_key[88 + x : 88 + x + 32] + padded_plaintext).digest()
    return msg_key_large[8:24]


def kdf_mtproto2(auth_key: bytes, msg_key: bytes, *, from_client: bool = True) -> tuple[bytes, bytes]:
    """Derive 32-byte aes_key and 32-byte aes_iv using MTProto 2.0 KDF."""
    if len(auth_key) != 256:
        raise MTProtoCryptoError(f"auth_key must be 256 bytes, got {len(auth_key)}")
    if len(msg_key) != 16:
        raise MTProtoCryptoError(f"msg_key must be 16 bytes, got {len(msg_key)}")
    x = 0 if from_client else 8
    sha256_a = hashlib.sha256(msg_key + auth_key[x : x + 36]).digest()
    sha256_b = hashlib.sha256(auth_key[40 + x : 40 + x + 36] + msg_key).digest()
    aes_key = sha256_a[0:8] + sha256_b[8:24] + sha256_a[24:32]
    aes_iv = sha256_b[0:8] + sha256_a[8:24] + sha256_b[24:32]
    return aes_key, aes_iv


class AuthKey:
    """2048-bit MTProto 2.0 authorization key with packet encryption/decryption."""

    __slots__ = ("key", "key_id_bytes", "key_id", "aux_hash")

    def __init__(self, key: bytes) -> None:
        if len(key) != 256:
            raise MTProtoCryptoError(f"AuthKey requires 256 bytes, got {len(key)}")
        self.key = key
        sha1 = hashlib.sha1(key).digest()
        self.aux_hash = sha1[:8]
        self.key_id_bytes = sha1[12:20]
        self.key_id = struct.unpack("<Q", self.key_id_bytes)[0]

    def encrypt_packet(self, inner_payload: bytes, *, from_client: bool = True) -> bytes:
        """Encrypt (salt + session_id + msg_id + seq_no + msg_len + msg) into MTProto 2.0 wire packet."""
        # Minimum 12 bytes of random padding; total must be divisible by 16
        pad_len = (16 - ((len(inner_payload) + 12) % 16)) % 16 + 12
        padded = inner_payload + os.urandom(pad_len)
        msg_key = compute_msg_key(self.key, padded, from_client=from_client)
        aes_key, aes_iv = kdf_mtproto2(self.key, msg_key, from_client=from_client)
        encrypted = aes_ige_encrypt(padded, aes_key, aes_iv)
        return self.key_id_bytes + msg_key + encrypted

    def decrypt_packet(self, packet: bytes, *, from_client: bool = False) -> bytes:
        """Decrypt and authenticate an MTProto 2.0 wire packet, returning the padded inner payload."""
        if len(packet) < 24 + 16:
            raise MTProtoCryptoError("MTProto packet too short")
        pkt_key_id = packet[:8]
        if pkt_key_id != self.key_id_bytes:
            raise MTProtoCryptoError("auth_key_id mismatch")
        msg_key = packet[8:24]
        ciphertext = packet[24:]
        if len(ciphertext) % 16 != 0:
            raise MTProtoCryptoError("Ciphertext length is not a multiple of 16")
        aes_key, aes_iv = kdf_mtproto2(self.key, msg_key, from_client=from_client)
        padded = aes_ige_decrypt(ciphertext, aes_key, aes_iv)
        expected_msg_key = compute_msg_key(self.key, padded, from_client=from_client)
        if msg_key != expected_msg_key:
            raise MTProtoCryptoError("msg_key verification failed (tampered or wrong key)")
        return padded


def rsa_fingerprint(n: int, e: int) -> int:
    """Compute signed 64-bit Telegram RSA public key fingerprint."""
    n_bytes = n.to_bytes((n.bit_length() + 7) // 8, "big")
    e_bytes = e.to_bytes((e.bit_length() + 7) // 8, "big")
    w = TLWriter()
    w.write_bytes(n_bytes)
    w.write_bytes(e_bytes)
    digest = hashlib.sha1(w.to_bytes()).digest()
    return struct.unpack("<q", digest[12:20])[0]


def rsa_encrypt_raw(data: bytes, n: int, e: int) -> bytes:
    """Raw textbook RSA encryption used in MTProto key exchange (256-byte big-endian block)."""
    if len(data) > 255:
        raise MTProtoCryptoError("RSA input must be <= 255 bytes")
    padded = data + os.urandom(255 - len(data))
    m = int.from_bytes(padded, "big")
    if m >= n:
        raise MTProtoCryptoError("RSA message integer >= modulus n")
    c = pow(m, e, n)
    return c.to_bytes(256, "big")


def factorize_pq(pq: int) -> tuple[int, int]:
    """Factorize a 64-bit semiprime pq into (p, q) with p <= q using Pollard's rho."""
    if pq <= 1:
        raise MTProtoCryptoError(f"Invalid pq: {pq}")
    if pq % 2 == 0:
        return (2, pq // 2) if 2 <= pq // 2 else (pq // 2, 2)

    rng = random.Random(0x5348495244414C)
    while True:
        y = rng.randrange(1, pq)
        c = rng.randrange(1, pq)
        m = 128
        g = 1
        r = 1
        q = 1
        x = y
        ys = y
        while g == 1:
            x = y
            for _ in range(r):
                y = (pow(y, 2, pq) + c) % pq
            k = 0
            while k < r and g == 1:
                ys = y
                for _ in range(min(m, r - k)):
                    y = (pow(y, 2, pq) + c) % pq
                    q = (q * abs(x - y)) % pq
                g = math.gcd(q, pq)
                k += m
            r <<= 1
        if g == pq:
            while True:
                ys = (pow(ys, 2, pq) + c) % pq
                g = math.gcd(abs(x - ys), pq)
                if g > 1:
                    break
        if g != pq:
            p = g
            other = pq // p
            return (p, other) if p <= other else (other, p)
