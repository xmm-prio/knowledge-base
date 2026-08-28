"""A running knowledge base with an MCP client attached.

Shared by the MCP test modules: every one of them asks its questions the way an agent does,
by tool name and JSON payload.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest_asyncio
from fastmcp import Client

from conftest import ManualSleep
from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.mcp import create_mcp_server
from knowledge_base.mcp.progress import HEARTBEAT


class StubUpstream:
    """Stands in for the supervised binary, answering with canned payloads."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool, arguments))
        answer = self.answers.get(tool, {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def arguments_for(self, tool: str) -> list[dict[str, object]]:
        return [arguments for name, arguments in self.calls if name == tool]


class Library:
    """A knowledge base, its MCP server, and a client talking to it."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        documents: DocumentService,
        upstream: StubUpstream,
        client: Client,
    ) -> None:
        self.root = root
        self.documents = documents
        self.upstream = upstream
        self.client = client
        self.progress: list[float] = []

    async def call(self, tool: str, **arguments: object) -> Any:
        result = await self.client.call_tool(tool, arguments, progress_handler=self._note_progress)
        return result.data

    async def _note_progress(
        self, progress: float, total: float | None, message: str | None
    ) -> None:
        self.progress.append(progress)

    def write(self, relative: str, text: str) -> None:
        path = self.root.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def text_of(self, relative: str) -> str:
        return (self.root.path / relative).read_text(encoding="utf-8")

    def place_repo(self, name: str) -> None:
        (self.root.codebase_dir / name / "src").mkdir(parents=True)
        (self.root.codebase_dir / name / "src" / "main.c").write_text("int main(void){}\n")


@asynccontextmanager
async def running(
    path: Path, upstream: StubUpstream | None = None, heartbeat: timedelta = HEARTBEAT
) -> AsyncIterator[Library]:
    """Bring up a knowledge base and an MCP client onto it."""
    root = KnowledgeBaseRoot(path)
    root.initialize()
    documents = DocumentService(root, sleep=ManualSleep())
    await documents.start()
    binary = upstream or StubUpstream()
    server = create_mcp_server(root, documents, CodeEngine(root, binary), heartbeat=heartbeat)
    try:
        async with Client(server) as client:
            yield Library(root, documents, binary, client)
    finally:
        await documents.stop()


@pytest_asyncio.fixture
async def library(tmp_path: Path) -> AsyncIterator[Library]:
    async with running(tmp_path) as started:
        yield started


__all__ = ["Library", "StubUpstream", "library", "running"]
