"""Tests for the file watcher.

knowledge/ is maintained by people -- through the web UI, through git pull, through an editor
on the server. The index only stays true if it hears about those changes.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from knowledge_base.docs.watcher import IndexWatcher
from knowledge_base.layout import KnowledgeBaseRoot

PATIENCE = 15.0


class Recorder:
    """Collects the paths the watcher reports."""

    def __init__(self) -> None:
        self.paths: set[str] = set()
        self._reported = asyncio.Event()

    async def __call__(self, paths: set[str]) -> None:
        self.paths |= paths
        self._reported.set()

    async def wait_for(self, path: str) -> None:
        async with asyncio.timeout(PATIENCE):
            while path not in self.paths:
                self._reported.clear()
                await self._reported.wait()


@pytest.fixture
def root(tmp_path: Path) -> KnowledgeBaseRoot:
    base = KnowledgeBaseRoot(tmp_path)
    base.initialize()
    return base


@pytest.fixture
async def recorder(root: KnowledgeBaseRoot) -> AsyncIterator[Recorder]:
    reported = Recorder()
    watcher = IndexWatcher(root, reported)
    await watcher.start()
    try:
        yield reported
    finally:
        await watcher.stop()


def write(root: KnowledgeBaseRoot, relative: str, text: str) -> Path:
    path = root.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestIndexWatcher:
    async def test_it_reports_knowledge_written_by_hand(
        self, root: KnowledgeBaseRoot, recorder: Recorder
    ) -> None:
        write(root, "knowledge/搬运.md", "# UB 搬运\n")

        await recorder.wait_for("knowledge/搬运.md")

    async def test_it_reports_a_learning_written_by_hand(
        self, root: KnowledgeBaseRoot, recorder: Recorder
    ) -> None:
        write(root, "learnings/ascendc/对齐.md", "# 对齐\n")

        await recorder.wait_for("learnings/ascendc/对齐.md")

    async def test_it_reports_a_document_that_was_deleted(
        self, root: KnowledgeBaseRoot, recorder: Recorder
    ) -> None:
        path = write(root, "knowledge/搬运.md", "# UB 搬运\n")
        await recorder.wait_for("knowledge/搬运.md")
        recorder.paths.clear()

        path.unlink()

        await recorder.wait_for("knowledge/搬运.md")

    async def test_it_stays_out_of_the_codebase(
        self, root: KnowledgeBaseRoot, recorder: Recorder
    ) -> None:
        """A codebase can be hundreds of thousands of files; the document index wants none."""
        write(root, "codebase/proj/README.md", "# 说明\n")
        write(root, "knowledge/搬运.md", "# UB 搬运\n")

        await recorder.wait_for("knowledge/搬运.md")

        assert recorder.paths == {"knowledge/搬运.md"}

    async def test_it_stays_out_of_the_runtime_directory(
        self, root: KnowledgeBaseRoot, recorder: Recorder
    ) -> None:
        """The index writes to its own database constantly; watching it would never settle."""
        write(root, ".knowledge-base/search.db-journal", "noise")
        write(root, "knowledge/搬运.md", "# UB 搬运\n")

        await recorder.wait_for("knowledge/搬运.md")

        assert recorder.paths == {"knowledge/搬运.md"}
