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

from knowledge_base.code.answers import read_call_chain, read_source, read_symbols
from knowledge_base.code.failures import InvalidQuery
from knowledge_base.code.grep import read_text_matches
from knowledge_base.code.projects import Catalog, NotIndexed, Project
from knowledge_base.layout import KnowledgeBaseRoot

logger = logging.getLogger(__name__)

DISAMBIGUATION = "#"
"""What a display name uses to separate two symbols that read alike. See `naming`."""

SEARCH_LIMIT = 50
"""Results to ask for per repository. The upstream truncates silently without this, and
reports `total` and `has_more` beside the page so a caller can say that it did."""

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

    KEYWORD = "keyword"
    """Rank declarations by how well they match these words. The upstream splits camelCase
    and weighs functions, routes and classes above the rest, so it finds a symbol whose exact
    spelling nobody remembers."""

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


def _search_request(mode: SearchMode, asked: str, limit: int) -> tuple[str, dict[str, object]]:
    """The upstream call one search mode is, with everything but the repository filled in.

    Three details here are the upstream's and not ours to reinvent: `search_code` greps and
    takes its needle as `pattern` with a `regex` flag beside it, `search_graph` matches names
    against a regular expression under `name_pattern` unless a ranked `query` is given -- in
    which case it ignores `name_pattern` entirely -- and both answer in a text tree unless
    asked for JSON.
    """
    if mode is SearchMode.TEXT:
        return "search_code", {"pattern": asked, "regex": False, "limit": limit}
    named = "query" if mode is SearchMode.KEYWORD else "name_pattern"
    return "search_graph", {named: asked, "limit": limit, "format": "json"}


class UnknownRepo(ValueError):
    """No repository by that name sits under `codebase/`."""


@dataclass(frozen=True)
class Scope:
    """One repository a question is actually asked about, under both of its names."""

    repo: str
    """The directory under `codebase/`. This is what a member sees and types."""

    project: str
    """What the upstream calls the same thing. Required by every read tool it offers."""


class Upstream(Protocol):
    """Whatever can answer an upstream tool call. The supervisor is the real one."""

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object: ...


READY = "ready"
"""The state `index_status` reports for a graph that will answer questions."""


@dataclass(frozen=True)
class IndexState:
    """What the upstream says about one repository's graph."""

    queryable: bool
    symbols: int | None = None
    """Nodes in the graph. A rough size, and a very quick way to spot a half-built one."""

    relations: int | None = None
    partial_files: int | None = None
    """Files the upstream parsed only in part. Every one of them is a place the call graph
    can be missing edges for a concrete, nameable reason."""


@dataclass(frozen=True)
class Repo:
    """One source repository an operator placed under `codebase/`."""

    name: str
    path: str
    """Relative to the knowledge base root, e.g. `codebase/mops`."""

    indexed: bool
    """Whether the upstream has a graph for it. On disk and searchable are different states."""

    symbols: int | None = None
    relations: int | None = None
    partial_files: int | None = None


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
        catalog = Catalog.best_effort(self._upstream)
        return [
            _repo(name, self._state_of(catalog.of(self._location(name))))
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
        return self._ask("get_architecture", self._one(repo), INCOMPLETE_CALL_GRAPH)

    def search_code(
        self,
        query: str,
        mode: SearchMode = SearchMode.SYMBOL,
        repo: str | None = None,
        limit: int = SEARCH_LIMIT,
    ) -> CodeAnswer:
        """Find code by declared name, by keyword, or by text when neither is remembered.

        The upstream searches one project at a time, so a question that names no repository
        is asked of every indexed one and the answers are laid end to end. They are not
        ranked against each other: the relevance the upstream computes is relative to the
        project it computed it in, and interleaving two such orders invents a third.
        """
        chosen = SearchMode(mode)
        tool, arguments = _search_request(chosen, _as_upstream_asks(query, chosen), limit)
        pages = [
            (scope.repo, self._ask(tool, arguments | {"project": scope.project}).payload)
            for scope in self._scopes(repo)
        ]
        read = read_text_matches if chosen is SearchMode.TEXT else read_symbols
        return CodeAnswer(payload=read(pages))

    def read_symbol(self, qualified_name: str, repo: str | None = None) -> CodeAnswer:
        """Read the source of one symbol, named the way the upstream names it.

        The name to hand in is `canonical_qn` from a search result. The short name beside it
        is for reading, and the upstream has never heard of it.
        """
        named = _canonical(qualified_name)
        answer = self._first_answer("get_code_snippet", {"qualified_name": named}, repo)
        source = read_source(answer.payload, qualified_name=named, repo=repo)
        return CodeAnswer(payload=source if source is not None else answer.payload)

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
        answer = self._first_answer(
            "trace_path",
            {
                "function_name": named,
                "direction": Direction(direction),
                "depth": depth,
                "format": "json",
                "include_evidence": True,
            },
            repo,
            INCOMPLETE_CALL_GRAPH,
        )
        chain = read_call_chain(
            answer.payload, root=named, direction=Direction(direction), repo=repo
        )
        return CodeAnswer(payload=chain, caveat=answer.caveat)

    def query_code_graph(self, cypher: str, repo: str) -> CodeAnswer:
        """Run a read-only openCypher query against one repository's graph.

        The one place an upstream interface reaches a caller unchanged, for the questions the
        capabilities above cannot phrase. See docs/adr/0002.
        """
        return self._ask("query_graph", {"query": cypher} | self._one(repo), INCOMPLETE_CALL_GRAPH)

    def _ask(
        self, tool: str, arguments: dict[str, object], caveat: str | None = None
    ) -> CodeAnswer:
        return CodeAnswer(payload=self._upstream.call_tool(tool, arguments), caveat=caveat)

    def _first_answer(
        self, tool: str, arguments: dict[str, object], repo: str | None, caveat: str | None = None
    ) -> CodeAnswer:
        """Ask about one symbol, in the repository given or in whichever one knows it.

        A canonical name identifies a symbol but does not say where it lives, and the caller
        that got it from a search may not have kept the repository beside it. Asking each in
        turn and stopping at the first answer is what a member would do by hand; the last
        refusal is what they hear if nobody knows the name.
        """
        scopes = self._scopes(repo)
        for position, scope in enumerate(scopes, start=1):
            try:
                return self._ask(tool, arguments | {"project": scope.project}, caveat)
            except Exception:
                if position == len(scopes):
                    raise
                logger.debug("%s does not answer for %s, trying the next", scope.repo, tool)
        raise NotIndexed("没有任何已索引的代码库")

    def _one(self, repo: str) -> dict[str, object]:
        """The `project` argument for a question that is about one named repository."""
        return {"project": self._scopes(repo)[0].project}

    def _scopes(self, repo: str | None) -> list[Scope]:
        """Every repository a question should reach, under the name the upstream wants.

        One when a repository was named, all the indexed ones when none was. A repository the
        upstream has no project for cannot be asked about at all, so that is said here rather
        than sent and refused for a missing argument.
        """
        catalog = Catalog.read_from(self._upstream)
        wanted = [self._verified(repo)] if repo is not None else self._present_names()
        found = [
            Scope(repo=name, project=project.name)
            for name in wanted
            if (project := catalog.of(self._location(name))) is not None
        ]
        if found:
            return found
        if repo is not None:
            raise NotIndexed(f"代码库 {repo} 尚未索引，请先在代码库页面索引它")
        raise NotIndexed("还没有任何代码库被索引，请先在代码库页面执行索引")

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

    def _state_of(self, project: Project | None) -> IndexState:
        """What the upstream will say about this repository if it is asked something.

        Being listed says it remembers indexing it, which is not the same as being able to
        search it now -- a half-written graph, a cache moved out from under it and a version
        mismatch all list fine and answer nothing. Displayed as "indexed", that difference
        costs a member the twenty minutes they spend not believing the search box.

        `index_status` is the upstream's own answer to exactly this question. It reports the
        size of the graph and which files it could not fully parse in the same breath, so the
        listing states those too rather than paying for them and throwing them away.
        """
        if project is None:
            return IndexState(queryable=False)
        try:
            reported = self._upstream.call_tool("index_status", {"project": project.name})
        except Exception as unanswered:  # noqa: BLE001 - any failure means "cannot query it"
            logger.info("%s is indexed but does not answer: %s", project.name, unanswered)
            return IndexState(queryable=False)
        return _read_state(reported)


def _as_upstream_asks(query: str, mode: SearchMode) -> str:
    """Turn what a member typed into what the upstream matches on.

    Only one of the modes hands a regular expression to something that reads it as one:
    `name_pattern` has no literal flag, so a symbol name is escaped before it goes there and
    `DataCopy(dst` stays a reasonable thing to remember rather than becoming an unbalanced
    parenthesis. Grep is told `regex: false` and keyword search tokenises, so both take what
    was typed. A pattern the caller meant as one is compiled here first, so an unbalanced
    bracket comes back saying where it is instead of as whatever the upstream makes of it.
    """
    asked = query.strip()
    if not asked:
        raise InvalidQuery("检索词不能为空")
    if mode is SearchMode.SYMBOL:
        return re.escape(asked)
    if mode is not SearchMode.REGEX:
        return asked
    try:
        re.compile(asked)
    except re.error as broken:
        raise InvalidQuery(f"这不是一个有效的正则：{broken}") from broken
    return asked


def _repo(name: str, state: IndexState) -> Repo:
    return Repo(
        name=name,
        path=f"codebase/{name}",
        indexed=state.queryable,
        symbols=state.symbols,
        relations=state.relations,
        partial_files=state.partial_files,
    )


def _read_state(reported: object) -> IndexState:
    """Read an `index_status` answer.

    A status the upstream states has to say `ready`; one it does not state at all is taken as
    ready, because the tool answering at all is the older, weaker evidence this used to rely
    on and losing it would mark a working repository unindexed.
    """
    if not isinstance(reported, dict):
        return IndexState(queryable=True)
    stated = reported.get("status")
    if isinstance(stated, str) and stated.strip().lower() != READY:
        logger.info("a repository reports its index as %r rather than ready", stated)
        return IndexState(queryable=False)
    partial = reported.get("parse_partial")
    files = partial.get("files") if isinstance(partial, dict) else None
    return IndexState(
        queryable=True,
        symbols=_count(reported.get("nodes")),
        relations=_count(reported.get("edges")),
        partial_files=len(files) if isinstance(files, list) else None,
    )


def _count(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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
