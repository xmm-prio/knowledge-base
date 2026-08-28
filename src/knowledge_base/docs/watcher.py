"""Hearing about documents that changed without going through this service.

knowledge/ is maintained by people: through the web UI, through a git pull on the server,
through an editor. Only knowledge/ and learnings/ are watched -- codebase/ is source, and
the runtime directory is where the index writes its own database.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from watchfiles import awatch

from knowledge_base.layout import KNOWLEDGE_DIRECTORY, LEARNINGS_DIRECTORY, KnowledgeBaseRoot

logger = logging.getLogger(__name__)

Changed = Callable[[set[str]], Awaitable[None]]
"""Told which paths, relative to the root, differ from what the index believes."""

WATCHED_DIRECTORIES = (KNOWLEDGE_DIRECTORY, LEARNINGS_DIRECTORY)


class IndexWatcher:
    """Reports document files that changed underneath the service."""

    def __init__(self, root: KnowledgeBaseRoot, changed: Changed) -> None:
        self._root = root
        self._changed = changed
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        for directory in WATCHED_DIRECTORIES:
            (self._root.path / directory).mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        task, self._task = self._task, None
        self._stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        directories = [str(self._root.path / directory) for directory in WATCHED_DIRECTORIES]
        async for batch in awatch(*directories, stop_event=self._stop):
            paths = {self._relative(Path(path)) for _, path in batch}
            try:
                await self._changed(paths)
            except Exception:
                logger.exception("Failed to take in changed documents: %s", sorted(paths))

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root.path).as_posix()
