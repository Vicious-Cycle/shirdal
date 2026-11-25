from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from shirdal.engine.fsm import FSMKey, FSMStorage


class SecretBox:
    """Authenticated symmetric encryption (Encrypt-then-MAC) with zero hard deps."""

    def __init__(self, secret: bytes | str) -> None:
        raw = secret.encode("utf-8") if isinstance(secret, str) else secret
        digest = hashlib.sha256(raw).digest()
        self._enc_key = hashlib.sha256(digest + b":enc").digest()
        self._mac_key = hashlib.sha256(digest + b":mac").digest()

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hashlib.sha256(
                self._enc_key + nonce + counter.to_bytes(4, "big")
            ).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    def encrypt(self, plaintext: bytes) -> str:
        nonce = secrets.token_bytes(16)
        stream = self._keystream(nonce, len(plaintext))
        ct = bytes(a ^ b for a, b in zip(plaintext, stream))
        mac = hmac.new(self._mac_key, nonce + ct, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + mac + ct).decode("ascii")

    def decrypt(self, token: str) -> bytes:
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise ValueError("Invalid encrypted token") from exc
        if len(raw) < 48:
            raise ValueError("Truncated encrypted token")
        nonce, mac, ct = raw[:16], raw[16:48], raw[48:]
        expected = hmac.new(self._mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("Authentication failed: tampered or wrong key")
        stream = self._keystream(nonce, len(ct))
        return bytes(a ^ b for a, b in zip(ct, stream))


class EncryptedStorage:
    """Transparent FSMStorage wrapper encrypting state names and data payloads."""

    def __init__(self, inner: FSMStorage, secret: bytes | str) -> None:
        self.inner = inner
        self.box = SecretBox(secret)

    async def get_state(self, key: FSMKey) -> str | None:
        raw = await self.inner.get_state(key)
        if raw is None:
            return None
        return self.box.decrypt(raw).decode("utf-8")

    async def set_state(self, key: FSMKey, state: str | None) -> None:
        if state is None:
            await self.inner.set_state(key, None)
            return
        token = self.box.encrypt(state.encode("utf-8"))
        await self.inner.set_state(key, token)

    async def get_data(self, key: FSMKey) -> dict[str, Any]:
        payload = await self.inner.get_data(key)
        blob = payload.get("__enc__")
        if blob is None:
            return {}
        return json.loads(self.box.decrypt(blob).decode("utf-8"))

    async def update_data(self, key: FSMKey, **kwargs: Any) -> dict[str, Any]:
        current = await self.get_data(key)
        current.update(kwargs)
        encoded = json.dumps(current, ensure_ascii=False).encode("utf-8")
        token = self.box.encrypt(encoded)
        await self.inner.update_data(key, __enc__=token)
        return current

    async def clear(self, key: FSMKey) -> None:
        await self.inner.clear(key)

    def close(self) -> None:
        close_fn = getattr(self.inner, "close", None)
        if callable(close_fn):
            close_fn()
