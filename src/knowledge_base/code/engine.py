"""The code domain, as the rest of the system sees it.

Every question about indexed source code goes through here. The upstream binary answers them,
but its tool names, argument spellings and payload shapes stop at this boundary.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from knowledge_base.code.answers import read_call_chain, read_symbols
from knowledge_base.code.failures import InvalidQuery
from knowledge_base.code.naming import repo_key
from knowledge_base.code.upstream import UpstreamUnavailable
from knowledge_base.layout import KnowledgeBaseRoot

logger = logging.getLogger(__name__)

DISAMBIGUATION = "#"
"""What a display name uses to separate two symbols that read alike. See `naming`."""

NEVER_MATCHES = "^$"
"""A symbol-name pattern nothing can satisfy: names are not empty. Used to ask the upstream
whether a repository's graph answers at all, without asking it to return anything."""

MAX_TRACE_DEPTH = 5
"""The upstream traverses at most five hops, and says so rather than truncating quietly."""

INCOMPLETE_CALL_GRAPH = (
    "调用图可能有漏边：上游只对 12 种语言做类型解析，其余语言的调用按文本匹配，"
    "解析不出来的调用不会成为边。没有边不等于没有调用。"
)
"""Attached to every answer read off the call graph. See docs/adr/0001."""


class SearchMode(StrEnum):
    """How to look for code. Genuinely different searches, not a filter over one.

    Ordinary text is the default in both of the first two, because the thing a member types
    into a box is the name they remember, not a pattern. Handing that to the upstream as a
    regular expression is how `DataCopy(` becomes an unbalanced-parenthesis error and how an
    empty result comes back for a symbol that is certainly there.
    """

    SYMBOL = "symbol"
    """Find declarations whose name contains this text, taken literally."""

    TEXT = "text"
    """Grep the indexed source. Finds comments, strings and unparsed languages too."""

    REGEX = "regex"
    """Match declared names against a regular expression, for someone who meant one."""


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
    SearchMode.REGEX: ("search_graph", "name_pattern"),
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
        """Every repository under `codebase/`, and whether it can be searched right now."""
        known = self._indexed_names()
        return [
            Repo(
                name=name,
                path=f"codebase/{name}",
                indexed=repo_key(name) in known and self._answers_about(name),
            )
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
        chosen = SearchMode(mode)
        tool, argument = _SEARCHES[chosen]
        asked = _as_upstream_asks(query, chosen)
        answer = self._ask(tool, {argument: asked} | self._scope(repo))
        if chosen is SearchMode.TEXT:
            return answer
        return CodeAnswer(payload=read_symbols(answer.payload, repo), caveat=answer.caveat)

    def read_symbol(self, qualified_name: str, repo: str | None = None) -> CodeAnswer:
        """Read the source of one symbol, named the way the upstream names it.

        The name to hand in is `canonical_qn` from a search result. The short name beside it
        is for reading, and the upstream has never heard of it.
        """
        return self._ask(
            "get_code_snippet", {"qualified_name": _canonical(qualified_name)} | self._scope(repo)
        )

    def trace_calls(
        self,
        symbol: str,
        direction: Direction = Direction.INBOUND,
        depth: int = 3,
        repo: str | None = None,
    ) -> CodeAnswer:
        """Walk the call graph from a symbol, up to `depth` hops."""
        if not 1 <= depth <= MAX_TRACE_DEPTH:
            raise InvalidQuery(f"深度只能是 1 到 {MAX_TRACE_DEPTH}，收到 {depth}")
        named = _canonical(symbol)
        answer = self._ask(
            "trace_path",
            {"function_name": named, "direction": Direction(direction), "depth": depth}
            | self._scope(repo),
            INCOMPLETE_CALL_GRAPH,
        )
        chain = read_call_chain(
            answer.payload, root=named, direction=Direction(direction), repo=repo
        )
        return CodeAnswer(payload=chain, caveat=answer.caveat)

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
        """Ask the upstream what it has, in a form that can be compared to a directory name.

        A silent binary must not hide what is on disk, so a failure here means every
        repository is listed as not indexed rather than not listed at all.
        """
        try:
            payload = self._upstream.call_tool("list_projects", {})
        except UpstreamUnavailable:
            # Not having an upstream is a state the caller is already told about, once, by
            # whoever tried to start it. Repeating it here as a traceback on every listing
            # would bury the reasons that are worth reading.
            logger.debug("no upstream to list indexed repositories")
            return set()
        except Exception:
            logger.warning("upstream could not list indexed repositories", exc_info=True)
            return set()
        return {repo_key(name) for name in _project_names(payload)}

    def _answers_about(self, repo: str) -> bool:
        """Whether the upstream can actually answer a question about this repository.

        Being listed says the upstream remembers indexing it, which is not the same as being
        able to search it now -- a half-written graph, a cache moved out from under it and a
        version mismatch all list fine and answer nothing. Displayed as "indexed", that
        difference costs a member the twenty minutes they spend not believing the search box.

        The probe is a symbol search for a pattern no name can match, so the upstream has to
        reach the repository's graph and has nothing to return from it. It runs only for
        repositories the upstream already claims, so a knowledge base of unindexed sources
        costs nothing to list.
        """
        try:
            self._upstream.call_tool(
                "search_graph", {"name_pattern": NEVER_MATCHES, "project": repo}
            )
        except Exception as unanswered:  # noqa: BLE001 - any failure means "cannot search it"
            logger.info("%s is listed by the upstream but cannot be searched: %s", repo, unanswered)
            return False
        return True


def _as_upstream_asks(query: str, mode: SearchMode) -> str:
    """Turn what a member typed into what the upstream matches on.

    The upstream takes a regular expression, so ordinary text has to be escaped rather than
    forwarded: `DataCopy(dst` is a syntax error as a pattern and a perfectly reasonable thing
    to remember about a function. A pattern the caller meant as one is checked here instead,
    so an unbalanced bracket comes back saying where it is rather than as whatever the
    upstream makes of it.
    """
    asked = query.strip()
    if not asked:
        raise InvalidQuery("检索词不能为空")
    if mode is not SearchMode.REGEX:
        return re.escape(asked) if mode is SearchMode.SYMBOL else asked
    try:
        re.compile(asked)
    except re.error as broken:
        raise InvalidQuery(f"这不是一个有效的正则：{broken}") from broken
    return asked


def _canonical(name: str) -> str:
    """Insist on the name the upstream knows, not the one the screen shows."""
    named = name.strip()
    if not named:
        raise InvalidQuery("要读取的符号名不能为空")
    if DISAMBIGUATION in named:
        raise InvalidQuery(
            f"{named!r} 是给人看的短名。请用检索结果里的 canonical_qn，它才是上游认得的限定名"
        )
    return named


def _project_names(payload: object) -> list[str]:
    """Read repository names out of an upstream listing.

    The upstream documents `list_projects` but not its payload shape, so this accepts both a
    bare list of entries and a mapping that wraps one.
    """
    entries = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    return [str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry]
