from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

JobFunc = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class ScheduledJob:
    interval: float
    func: JobFunc
    run_immediately: bool = False
    plugin_name: str | None = None
    task: asyncio.Task[Any] | None = field(default=None, repr=False)


class Scheduler:
    """Exception-isolated async periodic & one-shot scheduler."""

    def __init__(self, bot: Any) -> None:
        self._bot = bot
        self._jobs: list[ScheduledJob] = []
        self._one_shots: set[asyncio.Task[Any]] = set()
        self._running = False

    @property
    def jobs(self) -> list[ScheduledJob]:
        return list(self._jobs)

    async def _invoke(self, func: JobFunc) -> None:
        sig = inspect.signature(func)
        if len(sig.parameters) >= 1:
            await func(self._bot)
        else:
            await func()

    def _start_job(self, job: ScheduledJob) -> None:
        async def _runner() -> None:
            if not job.run_immediately:
                await asyncio.sleep(job.interval)
            while self._running:
                try:
                    await self._invoke(job.func)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                await asyncio.sleep(job.interval)

        job.task = asyncio.create_task(_runner())

    def add_periodic(
        self,
        interval: float,
        func: JobFunc,
        *,
        run_immediately: bool = False,
        plugin_name: str | None = None,
    ) -> ScheduledJob:
        if interval <= 0:
            raise ValueError("interval must be positive")
        job = ScheduledJob(
            interval=interval,
            func=func,
            run_immediately=run_immediately,
            plugin_name=plugin_name,
        )
        self._jobs.append(job)
        if self._running:
            self._start_job(job)
        return job

    def schedule_once(self, delay: float, func: JobFunc) -> asyncio.Task[Any]:
        async def _runner() -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._invoke(func)

        task = asyncio.create_task(_runner())
        self._one_shots.add(task)
        task.add_done_callback(self._one_shots.discard)
        return task

    def unregister_plugin(self, plugin_name: str) -> int:
        kept: list[ScheduledJob] = []
        removed = 0
        for job in self._jobs:
            if job.plugin_name == plugin_name:
                if job.task is not None and not job.task.done():
                    job.task.cancel()
                removed += 1
            else:
                kept.append(job)
        self._jobs = kept
        return removed

    def start(self) -> None:
        self._running = True
        for job in self._jobs:
            if job.task is None or job.task.done():
                self._start_job(job)

    async def stop(self) -> None:
        self._running = False
        tasks: list[asyncio.Task[Any]] = []
        for job in self._jobs:
            if job.task is not None and not job.task.done():
                job.task.cancel()
                tasks.append(job.task)
                job.task = None
        for t in list(self._one_shots):
            if not t.done():
                t.cancel()
                tasks.append(t)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._one_shots.clear()
