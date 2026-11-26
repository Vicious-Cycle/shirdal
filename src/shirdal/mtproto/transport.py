"""Zero-dependency asyncio TCP Abridged transport for MTProto 2.0."""

from __future__ import annotations

import asyncio
import socket
import struct


class MTProtoTransportError(OSError):
    """Raised on MTProto TCP framing or connection errors."""


class TCPAbridgedTransport:
    """Asyncio TCP Abridged transport (0xef header, 4-byte word framing)."""

    HEADER_BYTE = b"\xef"

    def __init__(self, host: str, port: int = 443, *, timeout: float = 15.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._send_lock = asyncio.Lock()
        self._header_sent = False

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if self.is_connected:
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, happy_eyeballs_delay=0.25),
            timeout=self.timeout,
        )
        sock = self._writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        self._header_sent = False

    async def close(self) -> None:
        if self._writer is None:
            return
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass
        self._reader = None
        self._writer = None
        self._header_sent = False

    async def send(self, payload: bytes) -> None:
        if not self.is_connected or self._writer is None:
            raise MTProtoTransportError("Transport is not connected.")
        if len(payload) % 4 != 0:
            raise MTProtoTransportError(f"Abridged payload must be 4-byte aligned, got {len(payload)} bytes.")

        words = len(payload) // 4
        if words < 127:
            frame_header = bytes([words])
        else:
            if words >= (1 << 24):
                raise MTProtoTransportError(f"Payload too large: {len(payload)} bytes")
            frame_header = b"\x7f" + words.to_bytes(3, "little")

        async with self._send_lock:
            if not self._header_sent:
                self._writer.write(self.HEADER_BYTE)
                self._header_sent = True
            self._writer.write(frame_header + payload)
            await self._writer.drain()

    async def recv(self) -> bytes:
        if not self.is_connected or self._reader is None:
            raise MTProtoTransportError("Transport is not connected.")

        try:
            first_raw = await self._reader.readexactly(1)
        except asyncio.IncompleteReadError as exc:
            raise MTProtoTransportError("Connection closed while reading frame header.") from exc

        first = first_raw[0]
        if first < 127:
            words = first
        elif first == 127:
            try:
                ext = await self._reader.readexactly(3)
            except asyncio.IncompleteReadError as exc:
                raise MTProtoTransportError("Connection closed while reading extended frame length.") from exc
            words = int.from_bytes(ext, "little")
        else:
            raise MTProtoTransportError(f"Invalid abridged frame prefix: 0x{first:02x}")

        length = words * 4
        try:
            data = await self._reader.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            raise MTProtoTransportError("Connection closed while reading frame payload.") from exc

        if length == 4:
            code = struct.unpack("<i", data)[0]
            if code < 0:
                raise MTProtoTransportError(f"MTProto transport error code: {code}")
        return data
