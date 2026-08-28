"""The document domain, running.

`DocumentStore` knows how to change one document; this is what keeps a whole knowledge base
consistent while several agents and several people work on it at once:

- every write goes through one queue, one at a time, because basic-memory has no conflict
  resolution and concurrent SQLite writers is a failure mode it acknowledges rather than
  handles. Reads never enter the queue.
- documents changed outside the service -- in the web UI, by a git pull, by hand -- are
  noticed and taken back into the index.
- the debounced auto-commit is driven by a heartbeat, so history reaches git without anyone
  asking for it.

This is the seam the MCP tools and the REST API sit on. Neither of them should reach past it
to the store, the queue or the graph.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import timedelta

from knowledge_base.docs.documents import Document
from knowledge_base.docs.graph import DocumentGraph, Neighbourhood
from knowledge_base.docs.notes import Learning, Observation
from knowledge_base.docs.search_index import Hit
from knowledge_base.docs.store import DocumentStore, Progress
from knowledge_base.docs.watcher import IndexWatcher
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.scheduling import Heartbeat, Sleep
from knowledge_base.writes import WriteQueue

QUIET_PERIOD = timedelta(seconds=30)
"""How long an author has to stay silent before their writes become one commit."""

COMMIT_INTERVAL = timedelta(seconds=5)
"""How often the service checks whether an author has gone quiet."""


class DocumentService:
    """Everything the rest of the system may do to documents."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        quiet_period: timedelta = QUIET_PERIOD,
        commit_interval: timedelta = COMMIT_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._store = DocumentStore(root, quiet_period=quiet_period, clock=clock)
        self._graph = DocumentGraph(root)
        self._writes = WriteQueue()
        self._watcher = IndexWatcher(root, self._take_in)
        self._heartbeat = Heartbeat(commit_interval, self._commit_if_quiet, sleep=sleep)

    async def start(self) -> None:
        await self._writes.start()
        await self._graph.start()
        await self._watcher.start()
        await self._heartbeat.start()

    async def stop(self) -> None:
        """Stop taking work, then make sure nothing written is left out of history."""
        await self._heartbeat.stop()
        await self._watcher.stop()
        await self._writes.submit(self._store.commit_now)
        await self._writes.stop()
        await self._graph.stop()

    async def search(self, query: str, limit: int = 20) -> list[Hit]:
        return self._store.search(query, limit=limit)

    async def read(self, relative_path: str) -> Document:
        return self._store.read(relative_path)

    async def explore_links(self, relative_path: str, depth: int = 1) -> Neighbourhood:
        """The documents this one is joined to, and how."""
        return await self._graph.neighbourhood(relative_path, depth=depth)

    async def create_learning(self, folder: str, learning: Learning) -> str:
        return await self._writes.submit(lambda: self._store.create_learning(folder, learning))

    async def append_to_learning(
        self, relative_path: str, author: str, observations: list[Observation]
    ) -> str:
        return await self._writes.submit(
            lambda: self._store.append_to_learning(relative_path, author, observations)
        )

    async def revise_learning(
        self, relative_path: str, author: str, replaces: str, replacement: Observation
    ) -> str:
        return await self._writes.submit(
            lambda: self._store.revise_learning(relative_path, author, replaces, replacement)
        )

    async def delete_learning(self, relative_path: str, author: str) -> None:
        await self._writes.submit(lambda: self._store.delete_learning(relative_path, author))

    async def rebuild(self, progress: Progress | None = None) -> int:
        """Read every document again, into both the search index and the graph.

        `progress` is called as the search index is rebuilt, so a caller bound by a tool-call
        timeout can keep reporting that it is alive.
        """
        indexed = await self._writes.submit(lambda: self._store.rebuild(progress))
        await self._graph.reindex()
        return indexed

    async def _take_in(self, paths: set[str]) -> None:
        def synchronize() -> None:
            for path in sorted(paths):
                self._store.synchronize(path)

        await self._writes.submit(synchronize)

    async def _commit_if_quiet(self) -> bool:
        return await self._writes.submit(self._store.commit_if_quiet)
