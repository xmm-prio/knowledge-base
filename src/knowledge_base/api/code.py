"""The code domain over HTTP.

Every answer here is the upstream's own JSON in an envelope. Two things make the envelope
necessary rather than decorative:

- the payload's shape is the upstream binary's, undocumented and unconfirmed, so nothing on
  this side may reach into it. It travels verbatim, and the page decides what to render.
- the upstream is a child process that can be missing, wedged or mid-restart. A code answer
  that failed is reported inside a 200 rather than as one, so a page showing code beside
  documents keeps the half that worked. Only a request that was wrong -- an unknown
  repository, an impossible depth -- is refused with a status.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from knowledge_base.api.dependencies import Bound
from knowledge_base.code.engine import (
    CodeAnswer,
    Direction,
    IndexOutcome,
    Repo,
    SearchMode,
    UnknownRepo,
)
from knowledge_base.code.failures import classify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/code", tags=["code"])


class CodeReply(BaseModel):
    """One answer from the code domain, or the reason there is none."""

    ok: bool
    payload: object = None
    """Either this service's own reading of the answer -- symbol matches, a call chain -- or,
    where nothing was worth reading into, the upstream's own JSON verbatim."""

    caveat: str | None = None
    """What the caller must not read into the payload -- the call graph has holes."""

    error: str | None = None

    kind: str | None = None
    """Which of the four failures this was, so the page can say who has to act on it."""

    diagnostic: str | None = None
    """The identifier this failure was logged under. Quotable to an operator."""


class RepoReply(BaseModel):
    """One repository under codebase/."""

    name: str
    path: str
    indexed: bool
    """On disk and searchable are different states, and the page shows both."""


class RepoListReply(BaseModel):
    repos: list[RepoReply]


class IndexReply(BaseModel):
    """What came of asking the upstream to index one repository."""

    repo: str
    ok: bool
    payload: object = None


class IndexRunReply(BaseModel):
    outcomes: list[IndexReply]


class CypherRequest(BaseModel):
    """The escape hatch, for questions the capabilities above cannot phrase."""

    cypher: str = Field(min_length=1)
    repo: str | None = None


async def ask(answer: Callable[[], CodeAnswer]) -> CodeReply:
    """Run one code-domain call off the event loop and wrap however it turns out.

    The engine is synchronous down to a pipe and a child process; awaiting it on the loop
    would stall every other request behind one slow graph query.
    """
    try:
        given = await asyncio.to_thread(answer)
    except UnknownRepo:
        # Asking about a repository that is not there is a wrong request, not a flaky
        # upstream, and the caller has to be able to tell those apart.
        raise
    except Exception as failure:  # noqa: BLE001 - the upstream's failures are data here
        trouble = classify(failure)
        return CodeReply(
            ok=False,
            error=trouble.message,
            kind=trouble.kind,
            diagnostic=trouble.diagnostic,
        )
    return CodeReply(ok=True, payload=given.payload, caveat=given.caveat)


def outcome(indexed: IndexOutcome) -> IndexReply:
    return IndexReply(repo=indexed.repo, ok=indexed.ok, payload=indexed.payload)


def repo(found: Repo) -> RepoReply:
    return RepoReply(name=found.name, path=found.path, indexed=found.indexed)


@router.get("/repos", summary="已纳管的代码库")
async def list_repos(bound: Bound) -> RepoListReply:
    found = await asyncio.to_thread(bound.code.list_repos)
    return RepoListReply(repos=[repo(one) for one in found])


@router.get("/repos/{name}/architecture", summary="一个代码库的架构概览")
async def architecture(name: str, bound: Bound) -> CodeReply:
    return await ask(lambda: bound.code.get_architecture(name))


@router.post("/repos/{name}/index", summary="重建一个代码库的索引")
async def index_repo(name: str, bound: Bound) -> IndexReply:
    return outcome(await asyncio.to_thread(bound.code.rebuild, name))


@router.get("/search", summary="按符号名或全文搜索代码")
async def search(
    bound: Bound,
    q: Annotated[
        str, Query(min_length=1, description="符号名或关键词，按字面处理；正则请用 mode=regex")
    ],
    mode: SearchMode = SearchMode.SYMBOL,
    repo: str | None = None,
) -> CodeReply:
    return await ask(lambda: bound.code.search_code(q, mode=mode, repo=repo))


@router.get("/symbol", summary="读一个符号的源码")
async def read_symbol(
    bound: Bound,
    name: Annotated[str, Query(min_length=1, description="canonical_qn，由符号搜索得到")],
    repo: str | None = None,
) -> CodeReply:
    return await ask(lambda: bound.code.read_symbol(name, repo=repo))


@router.get("/calls", summary="从一个符号出发追踪调用链")
async def trace_calls(
    bound: Bound,
    symbol: Annotated[str, Query(min_length=1)],
    direction: Direction = Direction.INBOUND,
    depth: Annotated[int, Query(ge=1, le=5)] = 3,
    repo: str | None = None,
) -> CodeReply:
    return await ask(
        lambda: bound.code.trace_calls(symbol, direction=direction, depth=depth, repo=repo)
    )


@router.post("/query", summary="直接对代码图跑一条只读 Cypher")
async def query_graph(request: CypherRequest, bound: Bound) -> CodeReply:
    return await ask(lambda: bound.code.query_code_graph(request.cypher, repo=request.repo))
