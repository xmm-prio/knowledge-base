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
from knowledge_base.docs.search_index import (
    Hit,
    IndexedDocument,
    IndexSize,
    SearchIndex,
    TagCount,
)
from knowledge_base.layout import (
    KNOWLEDGE_DIRECTORY,
    LEARNINGS_DIRECTORY,
    MARKDOWN_SUFFIX,
    KnowledgeBaseRoot,
)
from knowledge_base.vcs import DEFAULT_LOG_LENGTH, AutoCommitter, Repository, Revision

__all__ = [
    "MARKDOWN_SUFFIX",
    "DocumentStore",
    "LearningExists",
    "NoSuchDocument",
    "NoSuchLearning",
    "Progress",
]

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


class NoSuchDocument(ValueError):
    """The knowledge base holds no document at that path."""


class NoSuchLearning(NoSuchDocument):
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
        self._repository = Repository(root.path)
        self._committer = AutoCommitter(self._repository, quiet_period=quiet_period, clock=clock)

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
        """One document, reduced to what is indexed and displayed."""
        self._existing_document(relative_path)
        return load_document(self._root.path, relative_path)

    def read_text(self, relative_path: str) -> str:
        """One document's raw Markdown, exactly as it sits on disk.

        The editor is a source editor and the renderer is a separate pipeline, so text
        crosses this boundary unparsed in both directions (ADR-0005).
        """
        return self._existing_document(relative_path).read_text(encoding="utf-8")

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

    def write_document(self, relative_path: str, text: str, author: str) -> str:
        """Write a document as a person typed it, creating it if it is not there yet.

        The text is raw Markdown in and raw Markdown out: the web editor is a source editor,
        and re-serializing a document would rewrite every observation line (ADR-0005). This
        is the human write path -- wider than an agent's, since people maintain knowledge/ --
        and it shares the queue, the index update and the debounced commit with every other
        write.
        """
        path = self._root.resolve_document_file(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return self._write(path, text, author)

    def delete_document(self, relative_path: str, author: str) -> None:
        """Remove a document a person may edit. The file is recoverable from git."""
        path = self._existing_document(relative_path)
        path.unlink()
        self._index.remove(self._root.relative(path))
        self._committer.record(author, path)

    def restore(self, relative_path: str, revision: str, author: str) -> str | None:
        """Put a document back to the text it held at one revision.

        One document at a time, never a whole commit: a commit here aggregates whatever one
        author happened to write during a quiet period, so it is not a unit anybody meant.
        The old text is written as a new commit of its own, immediately -- history is
        appended to, never rewritten (ADR-0003), and a deliberate act should be visible the
        moment it happens.

        Returns the commit it made, or None when the document already held that text.
        """
        path = self._root.resolve_document_file(relative_path)
        text = self._repository.file_at(revision, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        relative = self._root.relative(path)
        self._index.put(load_document(self._root.path, relative))
        message = f"{author} 把 {relative} 回滚到 {revision[:8]}"
        if not self._committer.commit_alone(author, path, message):
            return None
        return self._repository.log(relative, limit=1)[0].revision

    def history(
        self, relative_path: str | None = None, limit: int = DEFAULT_LOG_LENGTH
    ) -> list[Revision]:
        """The commits touching one document, or the whole knowledge base, newest first."""
        return self._repository.log(relative_path, limit=limit)

    def revision_text(self, relative_path: str, revision: str) -> str:
        """A document's raw Markdown as it stood at one revision."""
        return self._repository.file_at(revision, relative_path)

    def timestamps(self, relative_path: str) -> tuple[str | None, str | None]:
        """When a document was created and last changed, read from git (ADR-0003)."""
        return self._repository.timestamps(relative_path)

    def paths_in(self, revision: str) -> list[str]:
        """The documents one commit touched."""
        return self._repository.paths_in(revision)

    def documents(self, tag: str | None = None) -> list[IndexedDocument]:
        """Every indexed document, optionally only those carrying one tag."""
        return self._index.documents(tag)

    def tag_counts(self) -> list[TagCount]:
        """Every tag in use, most used first."""
        return self._index.tag_counts()

    def size(self) -> IndexSize:
        """How much of the knowledge base is indexed."""
        return self._index.size()

    def _existing_document(self, relative_path: str) -> Path:
        path = self._root.resolve_document_file(relative_path)
        if not path.is_file():
            raise NoSuchDocument(f"no document at {relative_path}")
        return path

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
