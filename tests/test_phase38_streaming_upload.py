import asyncio
import hashlib
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from shirdal.core.native_mtproto_adapter import NativeMTProtoAdapter
from shirdal.mtproto import FileTransferManager


class TestPhase38StreamingUpload(unittest.IsolatedAsyncioTestCase):
    async def test_upload_stream_arbitrary_chunks_and_backpressure(self) -> None:
        mgr = FileTransferManager(chunk_size=1024, workers=2)
        payload = b"SHIRDAL_STREAM_" * 400  # 6000 bytes -> 6 parts
        stored: dict[int, bytes] = {}
        active = 0
        max_active = 0
        progress_events: list[tuple[int, int]] = []

        async def chunk_gen() -> AsyncIterator[bytes]:
            # Mix empty, tiny, and multi-chunk slices
            yield b""
            pos = 0
            sizes = [13, 3000, 7, 1500, 1480]
            for sz in sizes:
                if pos >= len(payload):
                    break
                yield payload[pos : pos + sz]
                pos += sz
            if pos < len(payload):
                yield payload[pos:]

        async def fake_save_part(
            file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
        ) -> bool:
            nonlocal active, max_active
            del file_id
            self.assertEqual(total_parts, 6)
            self.assertTrue(is_big)
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.005)
            stored[part_idx] = chunk
            active -= 1
            return True

        async def on_prog(done: int, total: int) -> None:
            progress_events.append((done, total))

        up = await mgr.upload_stream(
            chunk_gen(),
            len(payload),
            "stream.mp4",
            fake_save_part,
            progress=on_prog,
            big_threshold=2048,
        )
        self.assertTrue(up.is_big)
        self.assertEqual(up.parts, 6)
        self.assertIsNone(up.md5_checksum)
        self.assertLessEqual(max_active, 2)
        self.assertEqual(b"".join(stored[i] for i in range(6)), payload)
        self.assertEqual(progress_events[-1], (len(payload), len(payload)))

    async def test_upload_stream_small_md5_and_empty(self) -> None:
        mgr = FileTransferManager(chunk_size=1024, workers=2)
        small = b"hello shirdal stream"
        stored: dict[int, bytes] = {}

        async def small_gen() -> AsyncIterator[bytes]:
            yield small[:5]
            yield small[5:]

        async def fake_save_part(
            file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
        ) -> bool:
            del file_id, total_parts
            self.assertFalse(is_big)
            stored[part_idx] = chunk
            return True

        up = await mgr.upload_stream(
            small_gen(), len(small), "small.txt", fake_save_part, big_threshold=4096
        )
        self.assertFalse(up.is_big)
        self.assertEqual(up.parts, 1)
        self.assertEqual(up.md5_checksum, hashlib.md5(small).hexdigest())
        self.assertEqual(stored[0], small)

        async def empty_gen() -> AsyncIterator[bytes]:
            if False:
                yield b""

        empty_up = await mgr.upload_stream(
            empty_gen(), 0, "empty.bin", fake_save_part, big_threshold=4096
        )
        self.assertEqual(empty_up.parts, 1)
        self.assertEqual(empty_up.md5_checksum, hashlib.md5(b"").hexdigest())

    async def test_upload_stream_size_mismatch_and_error_cancellation(self) -> None:
        mgr = FileTransferManager(chunk_size=1024, workers=2)

        async def short_gen() -> AsyncIterator[bytes]:
            yield b"abc"

        async def ok_save(
            file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
        ) -> bool:
            del file_id, part_idx, total_parts, chunk, is_big
            return True

        with self.assertRaises(ValueError):
            await mgr.upload_stream(short_gen(), 100, "bad.bin", ok_save)

        with self.assertRaises(ValueError):
            await mgr.upload_stream(short_gen(), -1, "neg.bin", ok_save)

        async def fail_save(
            file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
        ) -> bool:
            del file_id, part_idx, total_parts, chunk, is_big
            return False

        async def multi_gen() -> AsyncIterator[bytes]:
            for _ in range(5):
                yield b"x" * 1024

        with self.assertRaises(RuntimeError):
            await mgr.upload_stream(multi_gen(), 5 * 1024, "fail.bin", fail_save)

    async def test_streaming_upload_file_and_download_file(self) -> None:
        mgr = FileTransferManager(chunk_size=1024, workers=2)
        payload = b"DISK_STREAM_" * 300  # 3600 bytes

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "video.mp4"
            src.write_bytes(payload)
            stored: dict[int, bytes] = {}

            async def save_part(
                file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
            ) -> bool:
                del file_id, total_parts, is_big
                stored[part_idx] = chunk
                return True

            up = await mgr.upload_file(src, save_part, big_threshold=2048)
            self.assertEqual(up.parts, 4)
            self.assertEqual(b"".join(stored[i] for i in range(4)), payload)

            async def get_part(offset: int, limit: int) -> bytes:
                return payload[offset : offset + limit]

            dst1 = Path(tmp) / "out_known.mp4"
            await mgr.download_file(dst1, get_part, total_size=len(payload))
            self.assertEqual(dst1.read_bytes(), payload)

            dst2 = Path(tmp) / "out_unknown.mp4"
            await mgr.download_file(dst2, get_part, total_size=None)
            self.assertEqual(dst2.read_bytes(), payload)

    async def test_native_adapter_send_stream_video_attributes(self) -> None:
        adapter = NativeMTProtoAdapter(api_id=1, api_hash="hash")
        adapter.self_id = 42
        calls: list[tuple[str, dict[str, Any]]] = []

        async def fake_call(method: str, **kwargs: Any) -> dict[str, Any]:
            calls.append((method, kwargs))
            if method == "messages.sendMedia":
                return {
                    "_": "updates",
                    "updates": [{"_": "updateMessageID", "id": 999, "random_id": kwargs["random_id"]}],
                    "users": [],
                    "chats": [],
                }
            return {"_": "boolTrue"}

        async def fake_input_peer(chat_id: int | str) -> dict[str, Any]:
            return {"_": "inputPeerUser", "user_id": int(chat_id), "access_hash": 0}

        adapter.call = fake_call  # type: ignore[method-assign]
        adapter._input_peer = fake_input_peer  # type: ignore[method-assign]

        video_bytes = b"MP4DATA_" * 100

        async def vid_gen() -> AsyncIterator[bytes]:
            yield video_bytes[:300]
            yield video_bytes[300:]

        ev = await adapter.send_stream(
            12345,
            vid_gen(),
            len(video_bytes),
            file_name="reel.mp4",
            caption="test reel",
            supports_streaming=True,
            duration=12.5,
            width=720,
            height=1280,
        )
        self.assertEqual(ev.id, 999)
        self.assertEqual(ev.text, "test reel")

        send_calls = [kw for m, kw in calls if m == "messages.sendMedia"]
        self.assertEqual(len(send_calls), 1)
        media = send_calls[0]["media"]
        self.assertEqual(media["_"], "inputMediaUploadedDocument")
        self.assertEqual(media["mime_type"], "video/mp4")
        attrs = media["attributes"]
        video_attrs = [a for a in attrs if a.get("_") == "documentAttributeVideo"]
        self.assertEqual(len(video_attrs), 1)
        self.assertTrue(video_attrs[0]["supports_streaming"])
        self.assertEqual(video_attrs[0]["duration"], 12.5)
        self.assertEqual(video_attrs[0]["w"], 720)
        self.assertEqual(video_attrs[0]["h"], 1280)
