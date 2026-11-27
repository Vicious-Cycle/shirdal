"""Small filesystem helpers."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def secure_file(path: str | Path | None) -> None:
    """Restrict a secret-bearing file (session / auth-key DB) to owner read/write (0600).

    Best effort: silently ignored on platforms or filesystems without POSIX permissions.
    SQLite copies the main file's mode to its -wal/-shm/-journal sidecars.
    """
    if path is None:
        return
    with contextlib.suppress(OSError, NotImplementedError):
        if os.path.exists(path):
            os.chmod(path, 0o600)
