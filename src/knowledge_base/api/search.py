"""Unified search.

One query, two answers, side by side and never merged. Documents and code are indexed by
different machinery with incomparable notions of relevance, so ranking them against each
other would invent a comparison neither index can make. The page shows two groups; this
endpoint hands it two groups.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from knowledge_base.api.code import CodeReply, ask
from knowledge_base.api.dependencies import Bound
from knowledge_base.code.engine import SearchMode
from knowledge_base.docs.search_index import Hit

router = APIRouter(tags=["search"])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class HitReply(BaseModel):
    """One document-side result: a whole document, or a single observation inside one."""

    kind: str
    """`document` or `observation`."""

    path: str
    title: str
    summary: str
    snippet: str
    """The matching observation, or the document's summary. Never the whole file."""

    score: float
    """Lower is better -- it is BM25, not a percentage."""


class DocumentsGroup(BaseModel):
    hits: list[HitReply]


class SearchReply(BaseModel):
    """The two domains' answers to one query, kept apart."""

    query: str
    documents: DocumentsGroup
    code: CodeReply


def hit(found: Hit) -> HitReply:
    return HitReply(
        kind=found.kind,
        path=found.path,
        title=found.title,
        summary=found.summary,
        snippet=found.snippet,
        score=found.score,
    )


@router.get("/search", summary="统一搜索：文档与代码分组返回")
async def search(
    bound: Bound,
    q: Annotated[str, Query(min_length=1, description="检索词，中文按 jieba 分词")],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    mode: SearchMode = SearchMode.SYMBOL,
    repo: str | None = None,
) -> SearchReply:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="查询词不能为空")
    found = await bound.documents.search(query, limit=limit)
    return SearchReply(
        query=query,
        documents=DocumentsGroup(hits=[hit(one) for one in found]),
        code=await ask(lambda: bound.code.search_code(query, mode=mode, repo=repo)),
    )
