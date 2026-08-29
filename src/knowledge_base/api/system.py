"""What the operator's status page needs.

Three questions: is anything broken, how much is actually indexed, and what does a colleague
have to paste into their opencode.json. The last one comes from the address resolver rather
than from the request that asked for it: a snippet is copied out of this page into files that
travel, so it has to name the address everyone can reach rather than the hostname one browser
happened to use. See `knowledge_base.address`.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from knowledge_base.address import NoRouteOutward
from knowledge_base.api.code import IndexRunReply, outcome
from knowledge_base.api.dependencies import Bound, Domains

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

MCP_PATH = "mcp"
"""Where the MCP endpoint is mounted. opencode only speaks Streamable HTTP here."""

MCP_SERVER_NAME = "kb"
"""The name a colleague's agent sees prefixed onto every tool: `kb_search_knowledge`."""


class DocumentsStatus(BaseModel):
    """How much of the document domain is indexed."""

    ok: bool
    documents: int
    observations: int
    tags: int
    error: str | None = None


class CodeStatus(BaseModel):
    """How the code domain and the binary behind it are doing."""

    ok: bool | None
    """None when nothing supervises the upstream, so its health is unknown rather than
    guessed at."""

    repos: int
    """Repositories an operator placed under codebase/."""

    indexed: int
    """How many of them the upstream can actually answer about."""

    error: str | None = None


class McpStatus(BaseModel):
    """What a colleague needs in order to point their agent at this service."""

    url: str
    """Empty when this machine has no address worth handing out; `error` says why."""

    opencode_config: str
    """The whole opencode.json fragment, ready to copy."""

    error: str | None = None


class StatusReply(BaseModel):
    documents: DocumentsStatus
    code: CodeStatus
    mcp: McpStatus


class ReindexRequest(BaseModel):
    repo: str | None = None
    """One repository, or every one of them."""


class DocumentIndexReply(BaseModel):
    indexed: int


def opencode_config(url: str) -> str:
    """The fragment from the deployment notes, with this service's address filled in."""
    return json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                MCP_SERVER_NAME: {
                    "type": "remote",
                    "url": url,
                    "enabled": True,
                    # Stated rather than left out, to skip a 401 probe and the warning it
                    # prints when there is no authentication to discover.
                    "oauth": False,
                }
            },
        },
        indent=2,
        ensure_ascii=False,
    )


async def _documents_status(bound: Domains) -> DocumentsStatus:
    try:
        size = await bound.documents.size()
    except Exception as failure:  # noqa: BLE001 - the page reports trouble, it does not raise
        logger.warning("the document index could not be measured: %s", failure)
        return DocumentsStatus(ok=False, documents=0, observations=0, tags=0, error=str(failure))
    return DocumentsStatus(
        ok=True, documents=size.documents, observations=size.observations, tags=size.tags
    )


async def _code_status(bound: Domains) -> CodeStatus:
    healthy = (
        None if bound.supervisor is None else await asyncio.to_thread(bound.supervisor.check_health)
    )
    try:
        repos = await asyncio.to_thread(bound.code.list_repos)
    except Exception as failure:  # noqa: BLE001 - same: a broken upstream is a status
        logger.warning("the code domain could not be listed: %s", failure)
        return CodeStatus(ok=False, repos=0, indexed=0, error=str(failure))
    return CodeStatus(
        ok=healthy, repos=len(repos), indexed=sum(1 for repo in repos if repo.indexed)
    )


def _mcp_status(bound: Domains) -> McpStatus:
    try:
        reachable = bound.address.advertised()
    except NoRouteOutward as unknown:
        logger.warning("no address to hand out: %s", unknown)
        return McpStatus(url="", opencode_config="", error=str(unknown))
    url = reachable.url(f"/{MCP_PATH}")
    return McpStatus(url=url, opencode_config=opencode_config(url))


@router.get("/status", summary="上游健康状况、索引规模与 MCP 接入片段")
async def status(bound: Bound) -> StatusReply:
    return StatusReply(
        documents=await _documents_status(bound),
        code=await _code_status(bound),
        mcp=_mcp_status(bound),
    )


@router.post("/reindex/documents", summary="重建文档索引")
async def reindex_documents(bound: Bound) -> DocumentIndexReply:
    return DocumentIndexReply(indexed=await bound.documents.rebuild())


@router.post("/reindex/code", summary="重建代码索引；不指定仓库则重建全部")
async def reindex_code(request: ReindexRequest, bound: Bound) -> IndexRunReply:
    if request.repo is not None:
        return IndexRunReply(
            outcomes=[outcome(await asyncio.to_thread(bound.code.rebuild, request.repo))]
        )
    everything = await asyncio.to_thread(lambda: list(bound.code.rebuild_all()))
    return IndexRunReply(outcomes=[outcome(one) for one in everything])
