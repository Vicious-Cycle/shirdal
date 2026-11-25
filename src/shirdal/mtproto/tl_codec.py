"""Fast, zero-dependency binary TL (Type Language) codec for MTProto 2.0."""

from __future__ import annotations

import gzip
import struct
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

BOOL_TRUE_ID = 0x997275B5
BOOL_FALSE_ID = 0xBC799737
VECTOR_ID = 0x1CB5C415
GZIP_PACKED_ID = 0x3072CFA1


class TLDecodeError(ValueError):
    """Raised when binary TL data is truncated or malformed."""


class TLWriter:
    """Zero-dependency little-endian TL binary serializer."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def write_raw(self, data: bytes | bytearray | memoryview) -> None:
        self._buf.extend(data)

    def write_int(self, value: int) -> None:
        self._buf.extend(struct.pack("<i", int(value)))

    def write_uint(self, value: int) -> None:
        self._buf.extend(struct.pack("<I", int(value) & 0xFFFFFFFF))

    def write_long(self, value: int) -> None:
        self._buf.extend(struct.pack("<q", int(value)))

    def write_int128(self, value: int | bytes) -> None:
        if isinstance(value, (bytes, bytearray)):
            if len(value) != 16:
                raise ValueError(f"int128 requires 16 bytes, got {len(value)}")
            self._buf.extend(value)
        else:
            self._buf.extend(int(value).to_bytes(16, "little", signed=False))

    def write_int256(self, value: int | bytes) -> None:
        if isinstance(value, (bytes, bytearray)):
            if len(value) != 32:
                raise ValueError(f"int256 requires 32 bytes, got {len(value)}")
            self._buf.extend(value)
        else:
            self._buf.extend(int(value).to_bytes(32, "little", signed=False))

    def write_double(self, value: float) -> None:
        self._buf.extend(struct.pack("<d", float(value)))

    def write_bool(self, value: bool) -> None:
        self.write_uint(BOOL_TRUE_ID if value else BOOL_FALSE_ID)

    def write_bytes(self, data: bytes) -> None:
        length = len(data)
        if length < 254:
            self._buf.append(length)
            total = 1 + length
        else:
            if length >= (1 << 24):
                raise ValueError(f"TL byte string too large: {length} bytes")
            self._buf.append(254)
            self._buf.extend(length.to_bytes(3, "little"))
            total = 4 + length
        self._buf.extend(data)
        pad = (-total) % 4
        if pad:
            self._buf.extend(b"\x00" * pad)

    def write_string(self, text: str) -> None:
        self.write_bytes(text.encode("utf-8"))

    def write_vector(
        self,
        items: Sequence[T],
        item_writer: Callable[[TLWriter, T], None],
        *,
        bare: bool = False,
    ) -> None:
        if not bare:
            self.write_uint(VECTOR_ID)
        self.write_uint(len(items))
        for item in items:
            item_writer(self, item)

    def to_bytes(self) -> bytes:
        return bytes(self._buf)


class TLReader:
    """Zero-copy little-endian TL binary deserializer."""

    __slots__ = ("_view", "_pos", "_len")

    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._view = memoryview(data)
        self._pos = 0
        self._len = len(self._view)

    @property
    def pos(self) -> int:
        return self._pos

    def remaining(self) -> int:
        return self._len - self._pos

    def _require(self, n: int) -> None:
        if self._pos + n > self._len:
            raise TLDecodeError(
                f"Unexpected EOF: needed {n} bytes, only {self.remaining()} remaining"
            )

    def read_raw(self, n: int) -> bytes:
        self._require(n)
        out = bytes(self._view[self._pos : self._pos + n])
        self._pos += n
        return out

    def read_int(self) -> int:
        self._require(4)
        val = struct.unpack_from("<i", self._view, self._pos)[0]
        self._pos += 4
        return int(val)

    def read_uint(self) -> int:
        self._require(4)
        val = struct.unpack_from("<I", self._view, self._pos)[0]
        self._pos += 4
        return int(val)

    def peek_uint(self) -> int:
        self._require(4)
        return int(struct.unpack_from("<I", self._view, self._pos)[0])

    def read_long(self) -> int:
        self._require(8)
        val = struct.unpack_from("<q", self._view, self._pos)[0]
        self._pos += 8
        return int(val)

    def read_int128_bytes(self) -> bytes:
        return self.read_raw(16)

    def read_int128(self) -> int:
        return int.from_bytes(self.read_raw(16), "little", signed=False)

    def read_int256_bytes(self) -> bytes:
        return self.read_raw(32)

    def read_int256(self) -> int:
        return int.from_bytes(self.read_raw(32), "little", signed=False)

    def read_double(self) -> float:
        self._require(8)
        val = struct.unpack_from("<d", self._view, self._pos)[0]
        self._pos += 8
        return float(val)

    def read_bool(self) -> bool:
        cid = self.read_uint()
        if cid == BOOL_TRUE_ID:
            return True
        if cid == BOOL_FALSE_ID:
            return False
        raise TLDecodeError(f"Invalid TL Bool constructor id: 0x{cid:08x}")

    def read_bytes(self) -> bytes:
        self._require(1)
        first = self._view[self._pos]
        if first < 254:
            length = int(first)
            header = 1
        elif first == 254:
            self._require(4)
            length = int.from_bytes(self._view[self._pos + 1 : self._pos + 4], "little")
            header = 4
        else:
            raise TLDecodeError("Invalid TL byte string length prefix 255")

        self._pos += header
        data = self.read_raw(length)
        pad = (-(header + length)) % 4
        if pad:
            self._require(pad)
            self._pos += pad
        return data

    def read_string(self) -> str:
        try:
            return self.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TLDecodeError(f"Invalid UTF-8 in TL string: {exc}") from exc

    def read_vector(
        self,
        item_reader: Callable[[TLReader], T],
        *,
        bare: bool = False,
    ) -> list[T]:
        if not bare:
            cid = self.read_uint()
            if cid != VECTOR_ID:
                raise TLDecodeError(f"Expected Vector (0x{VECTOR_ID:08x}), got 0x{cid:08x}")
        count = self.read_uint()
        return [item_reader(self) for _ in range(count)]


def pack_gzip(payload: bytes) -> bytes:
    """Wrap serialized TL bytes in gzip_packed#3072cfa1."""
    writer = TLWriter()
    writer.write_uint(GZIP_PACKED_ID)
    writer.write_bytes(gzip.compress(payload))
    return writer.to_bytes()


def unpack_gzip(reader: TLReader, *, expect_header: bool = True) -> bytes:
    """Unpack gzip_packed#3072cfa1 payload into raw bytes."""
    if expect_header:
        cid = reader.read_uint()
        if cid != GZIP_PACKED_ID:
            raise TLDecodeError(f"Expected gzip_packed (0x{GZIP_PACKED_ID:08x}), got 0x{cid:08x}")
    compressed = reader.read_bytes()
    try:
        return gzip.decompress(compressed)
    except OSError as exc:
        raise TLDecodeError(f"Invalid gzip_packed payload: {exc}") from exc
