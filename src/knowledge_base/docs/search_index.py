"""The gateway's own full-text index.

Upstream's FTS5 table is built with the unicode61 tokenizer, which treats a run of Han
characters as one indivisible token -- so a term sitting mid-sentence is unreachable. We
segment with jieba on the way in and on the way out, which turns Chinese retrieval back into
ordinary word matching. See ADR-0006.

Nothing here is a source of truth: the whole database can be deleted and rebuilt from files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import jieba

from knowledge_base.docs.documents import Document

DOCUMENT = "document"
OBSERVATION = "observation"

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(
    text,
    path UNINDEXED,
    kind UNINDEXED,
    title UNINDEXED,
    summary UNINDEXED,
    snippet UNINDEXED
);
CREATE TABLE IF NOT EXISTS document_tags (path TEXT NOT NULL, tag TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS document_tags_by_tag ON document_tags (tag);
CREATE INDEX IF NOT EXISTS document_tags_by_path ON document_tags (path);
"""


@dataclass(frozen=True)
class Hit:
    """One search result: either a whole document or a single observation inside one."""

    kind: str
    path: str
    title: str
    summary: str
    snippet: str
    score: float


@dataclass(frozen=True)
class IndexedDocument:
    """One document as the tree and the tag cloud list it, without its text."""

    path: str
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TagCount:
    """One tag, and how many documents carry it."""

    tag: str
    count: int


@dataclass(frozen=True)
class IndexSize:
    """How much of the knowledge base is indexed right now."""

    documents: int
    observations: int
    tags: int


class SearchIndex:
    """A rebuildable full-text index over the knowledge base's Markdown."""

    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(database)
        self._db.executescript(_SCHEMA)

    def put(self, document: Document) -> None:
        """Index a document, replacing whatever was indexed for its path."""
        self.remove(document.path)
        rows = [
            (
                _segment(
                    " ".join([document.title, document.summary, *document.tags, document.body])
                ),
                document.path,
                DOCUMENT,
                document.title,
                document.summary,
                document.summary or document.title,
            )
        ]
        rows += [
            (
                _segment(" ".join([observation.content, *observation.tags])),
                document.path,
                OBSERVATION,
                document.title,
                document.summary,
                observation.content,
            )
            for observation in document.observations
        ]
        self._db.executemany(
            "INSERT INTO entries (text, path, kind, title, summary, snippet) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._db.executemany(
            "INSERT INTO document_tags (path, tag) VALUES (?, ?)",
            [(document.path, tag) for tag in document.tags],
        )
        self._db.commit()

    def remove(self, path: str) -> None:
        """Drop everything indexed for a path."""
        self._db.execute("DELETE FROM entries WHERE path = ?", (path,))
        self._db.execute("DELETE FROM document_tags WHERE path = ?", (path,))
        self._db.commit()

    def documents(self, tag: str | None = None) -> list[IndexedDocument]:
        """Every indexed document, by path, optionally only those carrying one tag."""
        where = (
            "kind = ?"
            if tag is None
            else ("kind = ? AND path IN (SELECT path FROM document_tags WHERE tag = ?)")
        )
        parameters = (DOCUMENT,) if tag is None else (DOCUMENT, tag)
        rows = self._db.execute(
            f"SELECT path, title, summary FROM entries WHERE {where} ORDER BY path", parameters
        ).fetchall()
        tags = self._tags_by_path()
        return [
            IndexedDocument(path=path, title=title, summary=summary, tags=tags.get(path, []))
            for path, title, summary in rows
        ]

    def tag_counts(self) -> list[TagCount]:
        """Every tag in use, most used first, then alphabetically."""
        rows = self._db.execute(
            "SELECT tag, COUNT(*) AS uses FROM document_tags GROUP BY tag ORDER BY uses DESC, tag"
        ).fetchall()
        return [TagCount(tag=tag, count=uses) for tag, uses in rows]

    def size(self) -> IndexSize:
        """How much is indexed, for the status page."""
        counted = self._db.execute("SELECT kind, COUNT(*) FROM entries GROUP BY kind").fetchall()
        by_kind = dict(counted)
        (tags,) = self._db.execute("SELECT COUNT(DISTINCT tag) FROM document_tags").fetchone()
        return IndexSize(
            documents=by_kind.get(DOCUMENT, 0),
            observations=by_kind.get(OBSERVATION, 0),
            tags=tags,
        )

    def _tags_by_path(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for path, tag in self._db.execute(
            "SELECT path, tag FROM document_tags ORDER BY rowid"
        ).fetchall():
            grouped.setdefault(path, []).append(tag)
        return grouped

    def search(self, query: str, limit: int = 20) -> list[Hit]:
        """Find documents and observations matching a query, best first."""
        expression = _to_fts_expression(query)
        if not expression:
            return []
        rows = self._db.execute(
            "SELECT kind, path, title, summary, snippet, bm25(entries) AS score "
            "FROM entries WHERE entries MATCH ? ORDER BY score LIMIT ?",
            (expression, limit),
        ).fetchall()
        return [Hit(*row) for row in rows]

    def clear(self) -> None:
        """Empty the index so it can be rebuilt from files."""
        self._db.execute("DELETE FROM entries")
        self._db.execute("DELETE FROM document_tags")
        self._db.commit()

    def close(self) -> None:
        self._db.close()


def _segment(text: str) -> str:
    """Insert word boundaries Chinese does not write, so FTS5 can see individual terms."""
    return " ".join(jieba.cut_for_search(text))


def _to_fts_expression(query: str) -> str:
    """Build an FTS5 MATCH expression: every term of the query must appear, as a prefix."""
    terms = {term for token in jieba.cut_for_search(query) if (term := _quote(token))}
    return " AND ".join(sorted(terms))


def _quote(token: str) -> str:
    """Quote a token so punctuation cannot be read as FTS5 syntax."""
    cleaned = token.strip()
    if not any(character.isalnum() for character in cleaned):
        return ""
    return '"' + cleaned.replace('"', '""') + '"*'
