"""Documents over HTTP: browsing them, reading them, and editing them by hand.

Text crosses this boundary as raw Markdown in both directions. The editor is a source
editor and the renderer is a separate pipeline, because re-serializing a document would
escape every observation line and rewrite the corpus a byte at a time (ADR-0005).

Which paths a browser may name is decided in `layout`, not here: knowledge/ and learnings/,
Markdown only. There is no authentication in front of this, so that boundary is the only
one there is.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from knowledge_base.api.dependencies import Bound, Domains
from knowledge_base.docs.documents import Document
from knowledge_base.docs.graph import Neighbourhood
from knowledge_base.docs.notes import Observation
from knowledge_base.docs.search_index import IndexedDocument
from knowledge_base.layout import EDITABLE_DIRECTORIES

router = APIRouter(tags=["documents"])

MAX_DEPTH = 3


class DocumentSummary(BaseModel):
    """A document as a list or a card shows it, without its text."""

    path: str
    title: str
    summary: str
    tags: list[str]


class ObservationReply(BaseModel):
    """One independently searchable fact inside a document."""

    category: str
    content: str
    tags: list[str]


class DocumentReply(BaseModel):
    """One document, whole."""

    path: str
    title: str
    summary: str
    tags: list[str]

    text: str
    """The raw Markdown, exactly as it sits on disk."""

    observations: list[ObservationReply]

    created_at: str | None
    """First commit touching this document, ISO-8601. None while it is still waiting out
    the quiet period before its author's writes become a commit."""

    updated_at: str | None
    """Most recent commit touching this document."""


class DocumentWrite(BaseModel):
    """A document as a person just typed it."""

    text: str
    author: str = Field(min_length=1, description="谁写的；历史按作者归档")


class DocumentListReply(BaseModel):
    documents: list[DocumentSummary]


class TreeNode(BaseModel):
    """One folder of the knowledge base."""

    name: str
    path: str
    directories: list[TreeNode]
    documents: list[DocumentSummary]


class TreeReply(BaseModel):
    directories: list[TreeNode]


TreeNode.model_rebuild()


class TagReply(BaseModel):
    tag: str
    count: int


class TagCloudReply(BaseModel):
    tags: list[TagReply]


class LinkedReply(BaseModel):
    path: str
    title: str


class LinkReply(BaseModel):
    """A relation as it was written, from the document that holds the line."""

    type: str
    source: str
    target: str
    """Empty while the target document has not been written yet."""

    target_name: str


class NeighbourhoodReply(BaseModel):
    origin: str
    documents: list[LinkedReply]
    links: list[LinkReply]


def summary(document: IndexedDocument) -> DocumentSummary:
    return DocumentSummary(
        path=document.path,
        title=document.title,
        summary=document.summary,
        tags=list(document.tags),
    )


def observation(fact: Observation) -> ObservationReply:
    return ObservationReply(category=fact.category, content=fact.content, tags=list(fact.tags))


def document(
    parsed: Document, text: str, created: str | None, updated: str | None
) -> DocumentReply:
    return DocumentReply(
        path=parsed.path,
        title=parsed.title,
        summary=parsed.summary,
        tags=list(parsed.tags),
        text=text,
        observations=[observation(fact) for fact in parsed.observations],
        created_at=created,
        updated_at=updated,
    )


def neighbourhood(around: Neighbourhood) -> NeighbourhoodReply:
    return NeighbourhoodReply(
        origin=around.origin,
        documents=[LinkedReply(path=d.path, title=d.title) for d in around.documents],
        links=[
            LinkReply(
                type=link.type,
                source=link.source,
                target=link.target,
                target_name=link.target_name,
            )
            for link in around.links
        ],
    )


def tree(documents: list[IndexedDocument]) -> list[TreeNode]:
    """Fold a flat list of paths into the folders a person browses.

    The two document directories are always roots, even while empty: an empty knowledge base
    still has to show somewhere to put the first document.
    """
    roots = {
        name: TreeNode(name=name, path=name, directories=[], documents=[])
        for name in EDITABLE_DIRECTORIES
    }
    for indexed in documents:
        head, *rest = indexed.path.split("/")
        node = roots.get(head)
        if node is None or not rest:
            continue
        for folder in rest[:-1]:
            node = _folder(node, folder)
        node.documents.append(summary(indexed))
    return list(roots.values())


def _folder(parent: TreeNode, name: str) -> TreeNode:
    for existing in parent.directories:
        if existing.name == name:
            return existing
    made = TreeNode(name=name, path=f"{parent.path}/{name}", directories=[], documents=[])
    parent.directories.append(made)
    return made


@router.get("/tree", summary="目录树")
async def browse(bound: Bound) -> TreeReply:
    return TreeReply(directories=tree(await bound.documents.documents()))


@router.get("/tags", summary="标签云")
async def tags(bound: Bound) -> TagCloudReply:
    counted = await bound.documents.tag_cloud()
    return TagCloudReply(tags=[TagReply(tag=t.tag, count=t.count) for t in counted])


@router.get("/documents", summary="文档清单，可按标签筛选")
async def list_documents(bound: Bound, tag: str | None = None) -> DocumentListReply:
    listed = await bound.documents.documents(tag)
    return DocumentListReply(documents=[summary(one) for one in listed])


@router.get("/documents/{path:path}/links", summary="沿关系遍历一篇文档的邻域")
async def links(
    path: str, bound: Bound, depth: Annotated[int, Query(ge=1, le=MAX_DEPTH)] = 1
) -> NeighbourhoodReply:
    return neighbourhood(await bound.documents.explore_links(path, depth=depth))


@router.get("/documents/{path:path}", summary="读一篇文档的原始 Markdown")
async def read(path: str, bound: Bound) -> DocumentReply:
    text = await bound.documents.read_text(path)
    parsed = await bound.documents.read(path)
    created, updated = await bound.documents.timestamps(path)
    return document(parsed, text, created, updated)


@router.put("/documents/{path:path}", summary="写一篇文档；不存在则新建")
async def write(
    path: str, written: DocumentWrite, bound: Bound, response: Response
) -> DocumentReply:
    existed = await _exists(bound, path)
    relative = await bound.documents.write_document(path, written.text, written.author)
    response.status_code = 200 if existed else 201
    parsed = await bound.documents.read(relative)
    created, updated = await bound.documents.timestamps(relative)
    return document(parsed, written.text, created, updated)


@router.delete("/documents/{path:path}", status_code=204, summary="删除一篇文档")
async def delete(path: str, bound: Bound, author: Annotated[str, Query(min_length=1)]) -> Response:
    await bound.documents.delete_document(path, author)
    return Response(status_code=204)


async def _exists(bound: Domains, path: str) -> bool:
    try:
        await bound.documents.read_text(path)
    except Exception:  # noqa: BLE001 - a path that cannot be read is refused by the write
        return False
    return True
