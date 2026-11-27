"""MTProto 2.0 update sequence tracker (pts/qts/seq) and Peer access_hash cache."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from shirdal._fs import secure_file


class UpdateGapAction(StrEnum):
    APPLIED = "applied"
    IGNORED_DUPLICATE = "ignored_duplicate"
    GAP_DETECTED = "gap_detected"


@dataclass(slots=True, frozen=True)
class PeerRecord:
    peer_type: str  # user | chat | channel
    peer_id: int
    access_hash: int = 0
    username: str | None = None


class PeerCache:
    """In-memory and SQLite-backed cache for Telegram Peer access_hash values."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._peers: dict[tuple[str, int], PeerRecord] = {}
        self._usernames: dict[str, tuple[str, int]] = {}
        self._db_path = Path(db_path) if db_path is not None else None
        if self._db_path is not None:
            self._init_db()
            self._load_all()

    def _init_db(self) -> None:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mtproto_peers (
                    peer_type TEXT NOT NULL,
                    peer_id INTEGER NOT NULL,
                    access_hash INTEGER NOT NULL,
                    username TEXT,
                    PRIMARY KEY (peer_type, peer_id)
                )
                """
            )
            conn.commit()
        secure_file(self._db_path)

    def _load_all(self) -> None:
        assert self._db_path is not None
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT peer_type, peer_id, access_hash, username FROM mtproto_peers"
            ).fetchall()
        for ptype, pid, ahash, uname in rows:
            rec = PeerRecord(str(ptype), int(pid), int(ahash), str(uname) if uname else None)
            self._peers[(rec.peer_type, rec.peer_id)] = rec
            if rec.username:
                self._usernames[rec.username.lower()] = (rec.peer_type, rec.peer_id)

    def put(
        self,
        peer_type: str,
        peer_id: int,
        access_hash: int = 0,
        username: str | None = None,
    ) -> PeerRecord:
        norm_type = peer_type.lower()
        clean_user = username.lstrip("@") if username else None
        rec = PeerRecord(norm_type, int(peer_id), int(access_hash), clean_user)
        old = self._peers.get((norm_type, rec.peer_id))
        unchanged = (
            old is not None
            and old.access_hash == rec.access_hash
            and (clean_user is None or old.username == clean_user)
        )
        self._peers[(norm_type, rec.peer_id)] = rec
        if clean_user:
            self._usernames[clean_user.lower()] = (norm_type, rec.peer_id)

        if self._db_path is not None and not unchanged:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO mtproto_peers (peer_type, peer_id, access_hash, username)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(peer_type, peer_id) DO UPDATE SET
                        access_hash = excluded.access_hash,
                        username = COALESCE(excluded.username, mtproto_peers.username)
                    """,
                    (rec.peer_type, rec.peer_id, rec.access_hash, rec.username),
                )
                conn.commit()
        return rec

    def get(self, peer_type: str, peer_id: int) -> PeerRecord | None:
        return self._peers.get((peer_type.lower(), int(peer_id)))

    def get_by_username(self, username: str) -> PeerRecord | None:
        key = self._usernames.get(username.lstrip("@").lower())
        if key is None:
            return None
        return self._peers.get(key)


@dataclass(slots=True)
class UpdateStateTracker:
    """Tracks MTProto pts, qts, seq, and per-channel pts for gap-free updates."""

    pts: int = 0
    qts: int = 0
    seq: int = 0
    date: int = 0
    channel_pts: dict[int, int] = field(default_factory=dict)

    def apply_common_pts(self, new_pts: int, pts_count: int) -> UpdateGapAction:
        if self.pts == 0:
            self.pts = new_pts
            return UpdateGapAction.APPLIED
        expected = self.pts + pts_count
        if expected == new_pts:
            self.pts = new_pts
            return UpdateGapAction.APPLIED
        if expected > new_pts:
            return UpdateGapAction.IGNORED_DUPLICATE
        return UpdateGapAction.GAP_DETECTED

    def apply_qts(self, new_qts: int, qts_count: int = 1) -> UpdateGapAction:
        if self.qts == 0:
            self.qts = new_qts
            return UpdateGapAction.APPLIED
        expected = self.qts + qts_count
        if expected == new_qts:
            self.qts = new_qts
            return UpdateGapAction.APPLIED
        if expected > new_qts:
            return UpdateGapAction.IGNORED_DUPLICATE
        return UpdateGapAction.GAP_DETECTED

    def apply_channel_pts(self, channel_id: int, new_pts: int, pts_count: int) -> UpdateGapAction:
        cid = int(channel_id)
        cur = self.channel_pts.get(cid, 0)
        if cur == 0:
            self.channel_pts[cid] = new_pts
            return UpdateGapAction.APPLIED
        expected = cur + pts_count
        if expected == new_pts:
            self.channel_pts[cid] = new_pts
            return UpdateGapAction.APPLIED
        if expected > new_pts:
            return UpdateGapAction.IGNORED_DUPLICATE
        return UpdateGapAction.GAP_DETECTED

    def apply_seq(self, new_seq: int, seq_start: int | None = None) -> UpdateGapAction:
        if new_seq == 0:
            return UpdateGapAction.APPLIED
        start = new_seq if seq_start is None else seq_start
        if self.seq == 0:
            self.seq = new_seq
            return UpdateGapAction.APPLIED
        if self.seq + 1 == start:
            self.seq = new_seq
            return UpdateGapAction.APPLIED
        if self.seq + 1 > start:
            return UpdateGapAction.IGNORED_DUPLICATE
        return UpdateGapAction.GAP_DETECTED
