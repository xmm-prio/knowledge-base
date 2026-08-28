"""The MCP endpoint: ten first-party tools over Streamable HTTP.

Assembling the server is all this does. It is handed domains that are already running, so the
deployment stage decides what a process contains and this stage decides what an agent sees.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.mcp import code as code_tools
from knowledge_base.mcp import distilling, retrieval
from knowledge_base.mcp.failures import ToolFailures
from knowledge_base.mcp.instructions import compose, survey
from knowledge_base.mcp.progress import HEARTBEAT

logger = logging.getLogger(__name__)

SERVICE_NAME = "kb"
"""opencode prefixes tool names with it, so members see `kb_search_knowledge`."""

MCP_PATH = "/mcp"

SESSION_HEADER = b"mcp-session-id"
"""Streamable HTTP carries it on every request of an established session, so a POST without
one is a client arriving for the first time."""


def create_mcp_server(
    root: KnowledgeBaseRoot,
    documents: DocumentService,
    code: CodeEngine,
    heartbeat: timedelta = HEARTBEAT,
) -> FastMCP:
    """Build the MCP server over domains that are already running."""
    server: FastMCP = FastMCP(name=SERVICE_NAME, instructions=compose(survey(root, code)))
    server.add_middleware(ToolFailures())
    retrieval.install(server, documents)
    distilling.install(server, documents)
    code_tools.install(server, code, heartbeat)
    return server


def create_mcp_app(
    root: KnowledgeBaseRoot,
    documents: DocumentService,
    code: CodeEngine,
    heartbeat: timedelta = HEARTBEAT,
    path: str = MCP_PATH,
) -> Starlette:
    """The ASGI application to serve, with the outline refreshed for every arriving client."""
    server = create_mcp_server(root, documents, code, heartbeat=heartbeat)

    async def refresh() -> None:
        server.instructions = compose(await asyncio.to_thread(survey, root, code))

    return server.http_app(path=path, middleware=[Middleware(FreshOutline, refresh=refresh)])


class FreshOutline:
    """Rebuilds the instructions before a new client is told them.

    The outline has to describe the knowledge base as it is now, and `instructions` is read
    once, while a session is being established. A survey that fails is logged and the previous
    outline stands: an agent arriving with a slightly stale outline is a far smaller problem
    than an agent that cannot connect.
    """

    def __init__(self, app: ASGIApp, refresh: Callable[[], Awaitable[None]]) -> None:
        self._app = app
        self._refresh = refresh

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _is_new_session(scope):
            try:
                await self._refresh()
            except Exception:
                logger.exception("Could not survey the knowledge base for the outline")
        await self._app(scope, receive, send)


def _is_new_session(scope: Scope) -> bool:
    if scope["type"] != "http" or scope["method"] != "POST":
        return False
    return not any(name.lower() == SESSION_HEADER for name, _ in scope["headers"])
