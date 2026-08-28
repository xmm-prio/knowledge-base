"""Background work that has to keep happening for as long as the service is up."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class Heartbeat:
    """Calls an action on a fixed interval until it is stopped.

    Errors are logged and swallowed: the point of a heartbeat is that it keeps beating, and
    the caller is not there to be told.
    """

    def __init__(
        self,
        interval: timedelta,
        beat: Callable[[], Awaitable[object]],
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = interval.total_seconds()
        self._beat = beat
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            await self._sleep(self._interval)
            try:
                await self._beat()
            except Exception:
                logger.exception("Heartbeat action failed")
