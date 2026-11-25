from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

ProgressCallback = Callable[["TransferProgress"], Awaitable[Any] | Any]


@dataclass(slots=True, frozen=True)
class TransferProgress:
    current: int
    total: int
    percent: float
    speed_bps: float
    eta_seconds: float

    @property
    def human_current(self) -> str:
        return _fmt_bytes(self.current)

    @property
    def human_total(self) -> str:
        return _fmt_bytes(self.total)

    @property
    def human_speed(self) -> str:
        return f"{_fmt_bytes(int(self.speed_bps))}/s"

    def format_bar(self, width: int = 12) -> str:
        filled = int((self.percent / 100.0) * width)
        bar = "█" * filled + "░" * (width - filled)
        return (
            f"[{bar}] {self.percent:.1f}% • "
            f"{self.human_current}/{self.human_total} • {self.human_speed}"
        )


def _fmt_bytes(num: int) -> str:
    val = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024.0 or unit == "GB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} GB"


class ProgressTracker:
    """Throttled upload/download progress tracker to prevent FloodWait on status edits."""

    def __init__(
        self,
        callback: ProgressCallback,
        *,
        min_interval: float = 1.5,
        min_percent_step: float = 5.0,
    ) -> None:
        self.callback = callback
        self.min_interval = min_interval
        self.min_percent_step = min_percent_step
        self._start = time.monotonic()
        self._last_emit = 0.0
        self._last_pct = -min_percent_step
        self.emitted_count = 0

    async def report(self, current: int, total: int) -> None:
        if total <= 0:
            return
        now = time.monotonic()
        pct = min(100.0, (current / total) * 100.0)
        is_done = current >= total

        if not is_done:
            if (now - self._last_emit) < self.min_interval and (
                pct - self._last_pct
            ) < self.min_percent_step:
                return

        elapsed = max(1e-6, now - self._start)
        speed = current / elapsed
        eta = (total - current) / speed if speed > 0 else 0.0

        self._last_emit = now
        self._last_pct = pct
        self.emitted_count += 1

        prog = TransferProgress(
            current=current,
            total=total,
            percent=pct,
            speed_bps=speed,
            eta_seconds=eta,
        )
        res = self.callback(prog)
        if asyncio.iscoroutine(res):
            await res


class TransferQueue:
    """Bounded concurrency pool for heavy upload/download jobs."""

    def __init__(self, max_concurrent: int = 3) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._sem = asyncio.Semaphore(max_concurrent)
        self.active = 0
        self.max_seen_active = 0

    async def run(self, coro_fn: Callable[[], Awaitable[T]]) -> T:
        async with self._sem:
            self.active += 1
            if self.active > self.max_seen_active:
                self.max_seen_active = self.active
            try:
                return await coro_fn()
            finally:
                self.active -= 1
