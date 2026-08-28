"""The document-side tools an agent sees.

Retrieval here is deliberately thin: a match says what a document concluded and which of its
observations was hit, and nothing more. Full text costs an agent's context, so it is asked for
separately, by name -- that is what progressive disclosure means in this system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from knowledge_base.docs.documents import Document
from knowledge_base.docs.notes import Observation
from knowledge_base.docs.search_index import OBSERVATION, Hit
from knowledge_base.docs.service import DocumentService
from knowledge_base.docs.tags import normalize_tags
from knowledge_base.mcp.markdown import headings, section

DEFAULT_LIMIT = 8
"""How many documents a search answers with. Small on purpose: every one costs context."""

ROWS_PER_MATCH = 6
"""One document occupies one index row per observation, so more rows than matches are read."""


class Scope(StrEnum):
    """Which part of the knowledge base to search."""

    ALL = "all"
    KNOWLEDGE = "knowledge"
    LEARNINGS = "learnings"


@dataclass(frozen=True)
class Match:
    """One document a search found, disclosed down to what was hit inside it."""

    uri: str
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResults:
    matches: list[Match] = field(default_factory=list)


@dataclass(frozen=True)
class Content:
    """One document, disclosed in full or one section at a time."""

    uri: str
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    content: str = ""
    observations: list[str] = field(default_factory=list)
    """Every observation of the document, whatever section was asked for: they are facts of
    the document, not of a section."""


SEARCH_DESCRIPTION = (
    "检索知识库，返回标题、摘要、大纲与命中的观察原句，不返回全文；"
    "需要全文再用 read_knowledge 按 uri 取。动手排查前先搜一次。"
)

READ_DESCRIPTION = (
    "读一篇文档的全文；传 section 只读其中一节，section 取自 search_knowledge 给的大纲。"
)

EXPLORE_DESCRIPTION = "沿文档之间的关系游走，看这篇经验引用了什么、又被什么引用。"


@dataclass(frozen=True)
class Neighbour:
    """A document reachable from the one being explored."""

    uri: str
    title: str


@dataclass(frozen=True)
class Edge:
    """A relation as it was written, from the document that holds the line."""

    type: str
    source: str
    target: str
    """The document the relation points at, empty while nobody has written it yet."""

    target_title: str


@dataclass(frozen=True)
class Links:
    origin: str
    documents: list[Neighbour] = field(default_factory=list)
    links: list[Edge] = field(default_factory=list)


def install(server: FastMCP, documents: DocumentService) -> None:
    """Register the document-side tools on a server."""

    @server.tool(description=SEARCH_DESCRIPTION, annotations={"readOnlyHint": True})
    async def search_knowledge(
        query: Annotated[str, Field(description="检索词，可用中文")],
        scope: Annotated[Scope, Field(description="限定在知识或经验中检索")] = Scope.ALL,
        tags: Annotated[list[str] | None, Field(description="文档必须同时带有的标签")] = None,
        category: Annotated[str | None, Field(description="只要这一类观察，如 pitfall")] = None,
        limit: Annotated[int, Field(description="最多返回几篇文档", ge=1, le=20)] = DEFAULT_LIMIT,
    ) -> SearchResults:
        """Search documents and observations, disclosing only the first layer."""
        hits = await documents.search(query, limit=limit * ROWS_PER_MATCH)
        wanted = normalize_tags(tags or [])
        matches: list[Match] = []
        for path, sentences in _grouped(hits).items():
            if not _in_scope(path, Scope(scope)):
                continue
            document = await documents.read(path)
            if not set(wanted) <= set(document.tags):
                continue
            observations = _observations(document, sentences, category)
            if category is not None and not observations:
                continue
            matches.append(_match(document, observations))
            if len(matches) == limit:
                break
        return SearchResults(matches=matches)

    @server.tool(description=READ_DESCRIPTION, annotations={"readOnlyHint": True})
    async def read_knowledge(
        uri: Annotated[str, Field(description="文档路径，如 learnings/ascendc/对齐要求.md")],
        section: Annotated[str | None, Field(description="只读这一节，节名来自大纲")] = None,
    ) -> Content:
        """Read one document, or one section of it."""
        document = await documents.read(uri)
        return Content(
            uri=document.path,
            title=document.title,
            summary=document.summary,
            tags=document.tags,
            sections=headings(document.body),
            content=_body(document, section),
            observations=[_rendered(observation) for observation in document.observations],
        )

    @server.tool(description=EXPLORE_DESCRIPTION, annotations={"readOnlyHint": True})
    async def explore_links(
        uri: Annotated[str, Field(description="出发的文档路径")],
        depth: Annotated[int, Field(description="沿关系走几步", ge=1, le=3)] = 1,
    ) -> Links:
        """Walk the relations around one document."""
        neighbourhood = await documents.explore_links(uri, depth=depth)
        return Links(
            origin=neighbourhood.origin,
            documents=[
                Neighbour(uri=document.path, title=document.title)
                for document in neighbourhood.documents
            ],
            links=[
                Edge(
                    type=link.type,
                    source=link.source,
                    target=link.target,
                    target_title=link.target_name,
                )
                for link in neighbourhood.links
            ],
        )


def _grouped(hits: list[Hit]) -> dict[str, list[str]]:
    """Collapse index rows into one entry per document, best document first.

    A row is an observation when the index says so; a document-level row means the query met
    the title, the summary or the prose, and has no sentence to quote.
    """
    grouped: dict[str, list[str]] = {}
    for hit in hits:
        sentences = grouped.setdefault(hit.path, [])
        if hit.kind == OBSERVATION and hit.snippet not in sentences:
            sentences.append(hit.snippet)
    return grouped


def _in_scope(path: str, scope: Scope) -> bool:
    return scope is Scope.ALL or path.startswith(f"{scope.value}/")


def _observations(document: Document, sentences: list[str], category: str | None) -> list[str]:
    if category is None:
        return sentences
    of_category = {
        observation.content
        for observation in document.observations
        if observation.category == category
    }
    return [sentence for sentence in sentences if sentence in of_category]


def _body(document: Document, name: str | None) -> str:
    if name is None:
        return document.body
    found = section(document.body, name)
    if found is None:
        raise ToolError(
            f"{document.path} 没有名为 {name!r} 的小节，它有：{headings(document.body)}"
        )
    return found


def _rendered(observation: Observation) -> str:
    """An observation as it is written on disk, so an agent can quote it back to revise it."""
    tags = "".join(f" #{tag}" for tag in observation.tags)
    return f"[{observation.category}] {observation.content}{tags}"


def _match(document: Document, observations: list[str]) -> Match:
    return Match(
        uri=document.path,
        title=document.title,
        summary=document.summary,
        tags=document.tags,
        outline=headings(document.body),
        observations=observations,
    )
