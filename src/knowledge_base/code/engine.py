"""The code domain, as the rest of the system sees it.

Every question about indexed source code goes through here. The upstream binary answers them,
but its tool names, argument spellings and payload shapes stop at this boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from knowledge_base.layout import KnowledgeBaseRoot

logger = logging.getLogger(__name__)

MAX_TRACE_DEPTH = 5
"""The upstream traverses at most five hops, and says so rather than truncating quietly."""

INCOMPLETE_CALL_GRAPH = (
    "调用图可能有漏边：上游只对 12 种语言做类型解析，其余语言的调用按文本匹配，"
    "解析不出来的调用不会成为边。没有边不等于没有调用。"
)
"""Attached to every answer read off the call graph. See docs/adr/0001."""


class SearchMode(StrEnum):
    """How to look for code. The two modes are genuinely different searches, not a filter."""

    SYMBOL = "symbol"
    """Match declared names -- functions, classes, methods -- against a regular expression."""

    TEXT = "text"
    """Grep the indexed source. Finds comments, strings and unparsed languages too."""


class Direction(StrEnum):
    """Which way to walk the call graph from a symbol."""

    INBOUND = "inbound"
    """Who calls it."""

    OUTBOUND = "outbound"
    """What it calls."""

    BOTH = "both"


_SEARCHES = {
    SearchMode.SYMBOL: ("search_graph", "name_pattern"),
    SearchMode.TEXT: ("search_code", "query"),
}
"""Which upstream tool each mode is, and what it calls the thing being looked for."""


class UnknownRepo(ValueError):
    """No repository by that name sits under `codebase/`."""


class Upstream(Protocol):
    """Whatever can answer an upstream tool call. The supervisor is the real one."""

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class Repo:
    """One source repository an operator placed under `codebase/`."""

    name: str
    path: str
    """Relative to the knowledge base root, e.g. `codebase/mops`."""

    indexed: bool
    """Whether the upstream has a graph for it. On disk and searchable are different states."""


@dataclass(frozen=True)
class CodeAnswer:
    """One answer from the upstream, plus what the caller must not read into it."""

    payload: object
    """The upstream's own JSON, verbatim. Its shape is the upstream's, not ours."""

    caveat: str | None = None


@dataclass(frozen=True)
class IndexOutcome:
    """What came of asking the upstream to index one repository."""

    repo: str
    ok: bool
    payload: object
    """The upstream's own report when it answered, the failure description when it did not."""


class CodeEngine:
    """Repositories under `codebase/`, and the answers the upstream can give about them."""

    def __init__(self, root: KnowledgeBaseRoot, upstream: Upstream) -> None:
        self._root = root
        self._upstream = upstream

    def list_repos(self) -> list[Repo]:
        """Every repository under `codebase/`, and whether the upstream has indexed it."""
        indexed = self._indexed_names()
        return [
            Repo(name=name, path=f"codebase/{name}", indexed=name in indexed)
            for name in self._present_names()
        ]

    def rebuild_all(self) -> Iterator[IndexOutcome]:
        """Index every repository, yielding each outcome as it lands.

        Streaming rather than returning a list is what lets a caller report progress: the full
        rebuild runs far past the tool-call timeout of an agent that waits in silence.
        """
        for name in self._present_names():
            yield self._index(name)

    def rebuild(self, repo: str) -> IndexOutcome:
        """Index one repository from scratch."""
        return self._index(self._verified(repo))

    def get_architecture(self, repo: str) -> CodeAnswer:
        """Languages, packages, entry points, routes, hotspots and clusters of one repository."""
        return self._ask("get_architecture", self._scope(repo), INCOMPLETE_CALL_GRAPH)

    def search_code(
        self, query: str, mode: SearchMode = SearchMode.SYMBOL, repo: str | None = None
    ) -> CodeAnswer:
        """Find code by declared name, or by text when the name is not what you remember."""
        tool, argument = _SEARCHES[SearchMode(mode)]
        return self._ask(tool, {argument: query} | self._scope(repo))

    def read_symbol(self, qualified_name: str, repo: str | None = None) -> CodeAnswer:
        """Read the source of one symbol. Symbol search is how you learn its qualified name."""
        return self._ask("get_code_snippet", {"qualified_name": qualified_name} | self._scope(repo))

    def trace_calls(
        self,
        symbol: str,
        direction: Direction = Direction.INBOUND,
        depth: int = 3,
        repo: str | None = None,
    ) -> CodeAnswer:
        """Walk the call graph from a symbol, up to `depth` hops."""
        if not 1 <= depth <= MAX_TRACE_DEPTH:
            raise ValueError(f"depth must be between 1 and {MAX_TRACE_DEPTH}, not {depth}")
        return self._ask(
            "trace_path",
            {"function_name": symbol, "direction": Direction(direction), "depth": depth}
            | self._scope(repo),
            INCOMPLETE_CALL_GRAPH,
        )

    def query_code_graph(self, cypher: str, repo: str | None = None) -> CodeAnswer:
        """Run a read-only openCypher query against the graph.

        The one place an upstream interface reaches a caller unchanged, for the questions the
        capabilities above cannot phrase. See docs/adr/0002.
        """
        return self._ask(
            "query_graph", {"query": cypher} | self._scope(repo), INCOMPLETE_CALL_GRAPH
        )

    def _ask(
        self, tool: str, arguments: dict[str, object], caveat: str | None = None
    ) -> CodeAnswer:
        return CodeAnswer(payload=self._upstream.call_tool(tool, arguments), caveat=caveat)

    def _scope(self, repo: str | None) -> dict[str, object]:
        """Narrow a question to one repository, or leave it spanning the whole fleet."""
        return {"project": self._verified(repo)} if repo is not None else {}

    def _index(self, repo: str) -> IndexOutcome:
        """Index one repository whose name is already known to be real.

        A repository the upstream cannot digest is reported, not raised: a full rebuild has to
        leave every other repository searchable.
        """
        try:
            payload = self._upstream.call_tool(
                "index_repository", {"repo_path": str(self._location(repo))}
            )
        except Exception as failure:
            logger.warning("indexing %s failed: %s", repo, failure)
            return IndexOutcome(repo=repo, ok=False, payload=str(failure))
        return IndexOutcome(repo=repo, ok=True, payload=payload)

    def _verified(self, repo: str) -> str:
        if repo not in self._present_names():
            raise UnknownRepo(f"no repository named {repo!r} under codebase/")
        return repo

    def _location(self, repo: str) -> Path:
        """The upstream resolves paths against its own working directory, so hand it an absolute."""
        return self._root.codebase_dir / repo

    def _present_names(self) -> list[str]:
        directory = self._root.codebase_dir
        if not directory.is_dir():
            return []
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )

    def _indexed_names(self) -> set[str]:
        """Ask the upstream what it has. A silent binary must not hide what is on disk."""
        try:
            payload = self._upstream.call_tool("list_projects", {})
        except Exception:
            logger.warning("upstream could not list indexed repositories", exc_info=True)
            return set()
        return set(_project_names(payload))


def _project_names(payload: object) -> list[str]:
    """Read repository names out of an upstream listing.

    The upstream documents `list_projects` but not its payload shape, so this accepts both a
    bare list of entries and a mapping that wraps one.
    """
    entries = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    return [str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry]
