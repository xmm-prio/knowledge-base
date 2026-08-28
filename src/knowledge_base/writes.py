"""The one path by which anything changes the knowledge base.

basic-memory has no write conflict resolution, and SQLite lock contention under concurrent
writers is a failure mode it acknowledges rather than handles. So the gateway does not write
concurrently at all: every write is queued and carried out one at a time, in the order it was
submitted. Reads never enter this queue and stay fully concurrent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar

T = TypeVar("T")

_Job = tuple[Callable[[], Any], "asyncio.Future[Any]"]


class WriteQueue:
    """Serializes writes onto a single worker task."""

    def __init__(self) -> None:
        self._jobs: asyncio.Queue[_Job] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def submit(self, write: Callable[[], T]) -> T:
        """Carry out one write once every write submitted before it has finished."""
        done: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._jobs.put_nowait((write, done))
        return await done

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Finish the writes already submitted, then stop accepting work."""
        await self._jobs.join()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    async def __aenter__(self) -> WriteQueue:
        await self.start()
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop()

    async def _run(self) -> None:
        while True:
            write, done = await self._jobs.get()
            try:
                result = write()
            except Exception as error:  # noqa: BLE001 - the submitter decides what it means
                if not done.cancelled():
                    done.set_exception(error)
            else:
                if not done.cancelled():
                    done.set_result(result)
            finally:
                self._jobs.task_done()
