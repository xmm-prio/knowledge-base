"""The gateway's own full-text index.

Upstream's FTS5 table is built with the unicode61 tokenizer, which treats a run of Han
characters as one indivisible token -- so a term sitting mid-sentence is unreachable. We
segment with jieba on the way in and on the way out, which turns Chinese retrieval back into
ordinary word matching. See ADR-0006.

Nothing here is a source of truth: the whole database can be deleted and rebuilt from files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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
        self._db.commit()

    def remove(self, path: str) -> None:
        """Drop everything indexed for a path."""
        self._db.execute("DELETE FROM entries WHERE path = ?", (path,))
        self._db.commit()

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
