import hashlib
import tempfile
import unittest
from pathlib import Path

from shirdal.mtproto import (
    FileTransferManager,
    PeerCache,
    UpdateGapAction,
    UpdateStateTracker,
)


class TestPhase29MTProtoUpdatesFiles(unittest.IsolatedAsyncioTestCase):
    def test_peer_cache_memory_and_sqlite_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "peers.sqlite"
            cache = PeerCache(db)
            cache.put("user", 101, 999888777, username="@AliDev")
            cache.put("channel", 202, 555444333, username="shirdal_news")

            self.assertEqual(cache.get("user", 101).access_hash, 999888777)
            self.assertEqual(cache.get_by_username("alidev").peer_id, 101)

            # Reload from SQLite
            reloaded = PeerCache(db)
            self.assertEqual(reloaded.get("channel", 202).access_hash, 555444333)
            self.assertEqual(reloaded.get_by_username("@SHIRDAL_NEWS").peer_id, 202)

    def test_update_state_tracker_gap_and_duplicate_detection(self) -> None:
        tracker = UpdateStateTracker()
        self.assertEqual(tracker.apply_common_pts(100, 1), UpdateGapAction.APPLIED)
        self.assertEqual(tracker.apply_common_pts(101, 1), UpdateGapAction.APPLIED)
        self.assertEqual(tracker.apply_common_pts(101, 1), UpdateGapAction.IGNORED_DUPLICATE)
        self.assertEqual(tracker.apply_common_pts(105, 1), UpdateGapAction.GAP_DETECTED)

        self.assertEqual(tracker.apply_channel_pts(777, 10, 1), UpdateGapAction.APPLIED)
        self.assertEqual(tracker.apply_channel_pts(777, 12, 1), UpdateGapAction.GAP_DETECTED)

        self.assertEqual(tracker.apply_seq(50), UpdateGapAction.APPLIED)
        self.assertEqual(tracker.apply_seq(51, 51), UpdateGapAction.APPLIED)
        self.assertEqual(tracker.apply_seq(51, 51), UpdateGapAction.IGNORED_DUPLICATE)
        self.assertEqual(tracker.apply_seq(55, 54), UpdateGapAction.GAP_DETECTED)

    async def test_parallel_chunked_upload_and_download(self) -> None:
        mgr = FileTransferManager(chunk_size=1024, workers=4)
        payload = b"SHIRDAL_CHUNK_" * 300  # 4200 bytes -> 5 parts
        stored_parts: dict[int, bytes] = {}
        big_flags: list[bool] = []
        progress_events: list[tuple[int, int]] = []

        async def fake_save_part(
            file_id: int, part_idx: int, total_parts: int, chunk: bytes, is_big: bool
        ) -> bool:
            del file_id, total_parts
            stored_parts[part_idx] = chunk
            big_flags.append(is_big)
            return True

        async def on_prog(done: int, total: int) -> None:
            progress_events.append((done, total))

        uploaded = await mgr.upload_bytes(
            payload,
            "data.bin",
            fake_save_part,
            progress=on_prog,
            big_threshold=2048,  # force big file mode
        )
        self.assertTrue(uploaded.is_big)
        self.assertEqual(uploaded.parts, 5)
        self.assertIsNone(uploaded.md5_checksum)
        self.assertEqual(b"".join(stored_parts[i] for i in range(5)), payload)
        self.assertEqual(progress_events[-1], (len(payload), len(payload)))

        # Test small file mode with MD5
        small_up = await mgr.upload_bytes(b"hello", "hi.txt", fake_save_part, big_threshold=10240)
        self.assertFalse(small_up.is_big)
        self.assertEqual(small_up.md5_checksum, hashlib.md5(b"hello").hexdigest())

        # Test parallel download with known total_size
        async def fake_get_part(offset: int, limit: int) -> bytes:
            return payload[offset : offset + limit]

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.bin"
            await mgr.download_file(dest, fake_get_part, total_size=len(payload))
            self.assertEqual(dest.read_bytes(), payload)

        # Test sequential download when total_size is unknown
        seq_data = await mgr.download_bytes(fake_get_part, total_size=None)
        self.assertEqual(seq_data, payload)
