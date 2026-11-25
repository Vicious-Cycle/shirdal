"""Parallel chunked file upload and download manager for MTProto 2.0."""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHUNK_SIZE = 512 * 1024  # 512 KiB (maximum Telegram MTProto part size)
BIG_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MiB

ProgressFn = Callable[[int, int], Awaitable[None] | None]


@dataclass(slots=True, frozen=True)
class UploadedFile:
    file_id: int
    parts: int
    name: str
    is_big: bool
    md5_checksum: str | None = None


class FileTransferManager:
    """Concurrent chunked uploader/downloader decoupled from raw transport."""

    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        workers: int = 4,
    ) -> None:
        if chunk_size <= 0 or chunk_size % 1024 != 0 or DEFAULT_CHUNK_SIZE % chunk_size != 0:
            raise ValueError("chunk_size must be a positive multiple of 1024 dividing 512 KiB.")
        self.chunk_size = int(chunk_size)
        self.workers = max(1, int(workers))

    async def _emit_progress(self, cb: ProgressFn | None, done: int, total: int) -> None:
        if cb is None:
            return
        res = cb(done, total)
        if asyncio.iscoroutine(res):
            await res

    async def upload_bytes(
        self,
        data: bytes,
        name: str,
        save_part_fn: Callable[[int, int, int, bytes, bool], Awaitable[bool]],
        *,
        progress: ProgressFn | None = None,
        big_threshold: int = BIG_FILE_THRESHOLD,
    ) -> UploadedFile:
        total = len(data)
        file_id = struct.unpack("<q", os.urandom(8))[0]
        is_big = total > big_threshold
        parts = max(1, (total + self.chunk_size - 1) // self.chunk_size)
        md5_hex = None if is_big else hashlib.md5(data).hexdigest()

        sem = asyncio.Semaphore(self.workers)
        uploaded_bytes = 0
        lock = asyncio.Lock()

        async def _send_part(part_idx: int) -> None:
            nonlocal uploaded_bytes
            start = part_idx * self.chunk_size
            chunk = data[start : start + self.chunk_size]
            async with sem:
                ok = await save_part_fn(file_id, part_idx, parts, chunk, is_big)
                if not ok:
                    raise RuntimeError(f"Failed to upload file part {part_idx}/{parts}")
            async with lock:
                uploaded_bytes += len(chunk)
                await self._emit_progress(progress, uploaded_bytes, total)

        await asyncio.gather(*(_send_part(i) for i in range(parts)))
        return UploadedFile(
            file_id=file_id,
            parts=parts,
            name=name,
            is_big=is_big,
            md5_checksum=md5_hex,
        )

    async def upload_file(
        self,
        path: str | Path,
        save_part_fn: Callable[[int, int, int, bytes, bool], Awaitable[bool]],
        *,
        progress: ProgressFn | None = None,
        big_threshold: int = BIG_FILE_THRESHOLD,
    ) -> UploadedFile:
        p = Path(path)
        return await self.upload_bytes(
            p.read_bytes(),
            p.name,
            save_part_fn,
            progress=progress,
            big_threshold=big_threshold,
        )

    async def download_bytes(
        self,
        get_part_fn: Callable[[int, int], Awaitable[bytes]],
        *,
        total_size: int | None = None,
        progress: ProgressFn | None = None,
    ) -> bytes:
        if total_size is not None:
            offsets = list(range(0, total_size, self.chunk_size))
            if not offsets:
                return b""
            sem = asyncio.Semaphore(self.workers)
            results: list[bytes] = [b""] * len(offsets)
            downloaded = 0
            lock = asyncio.Lock()

            async def _fetch(idx: int, offset: int) -> None:
                nonlocal downloaded
                async with sem:
                    chunk = await get_part_fn(offset, self.chunk_size)
                results[idx] = chunk
                async with lock:
                    downloaded += len(chunk)
                    await self._emit_progress(progress, downloaded, total_size)

            await asyncio.gather(*(_fetch(i, off) for i, off in enumerate(offsets)))
            return b"".join(results)

        # Sequential fallback when total_size is unknown
        buf = bytearray()
        offset = 0
        while True:
            chunk = await get_part_fn(offset, self.chunk_size)
            if not chunk:
                break
            buf.extend(chunk)
            offset += len(chunk)
            await self._emit_progress(progress, len(buf), len(buf))
            if len(chunk) < self.chunk_size:
                break
        return bytes(buf)

    async def download_file(
        self,
        destination: str | Path,
        get_part_fn: Callable[[int, int], Awaitable[bytes]],
        *,
        total_size: int | None = None,
        progress: ProgressFn | None = None,
    ) -> Path:
        data = await self.download_bytes(get_part_fn, total_size=total_size, progress=progress)
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest
