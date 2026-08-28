"""The document domain, as the rest of the system sees it.

Everything that reads or writes Markdown in the knowledge base goes through here: the files
are the source of truth, the search index is derived from them, and git records what changed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from knowledge_base.docs.documents import Document, load_document
from knowledge_base.docs.notes import (
    Learning,
    Observation,
    append_observations,
    render_learning,
    replace_observation,
)
from knowledge_base.docs.search_index import Hit, SearchIndex
from knowledge_base.layout import (
    KNOWLEDGE_DIRECTORY,
    LEARNINGS_DIRECTORY,
    KnowledgeBaseRoot,
)
from knowledge_base.vcs import AutoCommitter, Repository

MARKDOWN_SUFFIX = ".md"

INDEXED_DIRECTORIES = (KNOWLEDGE_DIRECTORY, LEARNINGS_DIRECTORY)
"""codebase/ is deliberately absent: it holds source, and there can be an enormous amount
of it. Code is searchable through the code domain instead."""

Progress = Callable[[int, int], None]
"""Told how many documents of how many are done, so long work can report it is still alive."""


def _is_indexed(relative_path: str) -> bool:
    head, _, tail = relative_path.replace("\\", "/").partition("/")
    return bool(tail) and head in INDEXED_DIRECTORIES and relative_path.endswith(MARKDOWN_SUFFIX)


class LearningExists(ValueError):
    """A learning is already written there. Append to it or revise it instead."""


class NoSuchLearning(ValueError):
    """There is no learning, or no observation, matching what the caller named."""


class DocumentStore:
    """Files, search index and version history, kept in step."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        quiet_period: timedelta,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = root
        self._index = SearchIndex(root.runtime_dir / "search.db")
        self._committer = AutoCommitter(
            Repository(root.path), quiet_period=quiet_period, clock=clock
        )

    def commit_if_quiet(self) -> bool:
        """Commit pending writes if their author has gone quiet. Called on a timer."""
        return self._committer.flush_due()

    def commit_now(self) -> bool:
        """Commit pending writes without waiting. Called on shutdown."""
        return self._committer.flush_now()

    def rebuild(self, progress: Progress | None = None) -> int:
        """Reindex every document from disk. The index holds nothing files do not.

        `progress` is called after each document with how far along the rebuild is, so a
        caller bound by a tool-call timeout can keep saying it is still alive.
        """
        self._index.clear()
        paths = self._markdown_paths()
        for done, relative in enumerate(paths, start=1):
            self._index.put(load_document(self._root.path, relative))
            if progress is not None:
                progress(done, len(paths))
        return len(paths)

    def synchronize(self, relative_path: str) -> None:
        """Make the index agree with disk for one path.

        knowledge/ is edited by hand and by git as well as through this service, so the index
        has to be told what changed rather than assuming it made the change itself.
        """
        if not _is_indexed(relative_path):
            return
        path = self._root.path / relative_path
        if path.is_file():
            self._index.put(load_document(self._root.path, relative_path))
        else:
            self._index.remove(relative_path)

    def search(self, query: str, limit: int = 20) -> list[Hit]:
        return self._index.search(query, limit=limit)

    def read(self, relative_path: str) -> Document:
        return load_document(self._root.path, relative_path)

    def create_learning(self, folder: str, learning: Learning) -> str:
        """Write a new learning. Returns its path relative to the root."""
        path = self._root.resolve_learning_path(folder, learning.title)
        if path.exists():
            raise LearningExists(f"{self._root.relative(path)} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        return self._write(path, render_learning(learning), learning.author)

    def append_to_learning(
        self, relative_path: str, author: str, observations: list[Observation]
    ) -> str:
        """Add observations to a learning that already exists."""
        path = self._existing_learning(relative_path)
        text = path.read_text(encoding="utf-8")
        return self._write(path, append_observations(text, observations), author)

    def revise_learning(
        self, relative_path: str, author: str, replaces: str, replacement: Observation
    ) -> str:
        """Overwrite a rotten observation. The old wording is only in git afterwards."""
        path = self._existing_learning(relative_path)
        revised = replace_observation(path.read_text(encoding="utf-8"), replaces, replacement)
        if revised is None:
            raise NoSuchLearning(f"{relative_path} has no observation saying {replaces!r}")
        return self._write(path, revised, author)

    def delete_learning(self, relative_path: str, author: str) -> None:
        """Remove a learning entirely. The file is recoverable from git."""
        path = self._existing_learning(relative_path)
        path.unlink()
        self._index.remove(relative_path)
        self._committer.record(author, path)

    def _existing_learning(self, relative_path: str) -> Path:
        path = self._root.resolve_learning_file(relative_path)
        if not path.is_file():
            raise NoSuchLearning(f"no learning at {relative_path}")
        return path

    def _write(self, path: Path, text: str, author: str) -> str:
        """The one place a document reaches disk: write, reindex, queue the commit."""
        path.write_text(text, encoding="utf-8")
        relative = self._root.relative(path)
        self._index.put(load_document(self._root.path, relative))
        self._committer.record(author, path)
        return relative

    def _markdown_paths(self) -> list[str]:
        paths: list[str] = []
        for directory in INDEXED_DIRECTORIES:
            base = self._root.path / directory
            if not base.is_dir():
                continue
            paths += [
                self._relative(path)
                for path in sorted(base.rglob(f"*{MARKDOWN_SUFFIX}"))
                if path.is_file()
            ]
        return paths

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root.path).as_posix()
