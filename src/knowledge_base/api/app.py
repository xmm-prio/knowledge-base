"""The REST API, assembled.

One factory that takes the two domains already built and hands back an ASGI app. It starts
nothing and owns nothing: whoever built the domains keeps their lifecycle, so the same app
can be mounted beside the MCP endpoint in the real server or driven straight from a test.

The API is unauthenticated by design -- the service is reachable only inside the network it
is deployed on -- which is exactly why every path a browser can name is bounded by the
domains below rather than by anything here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from knowledge_base.address import Address, RoutedAddress
from knowledge_base.api import code as code_routes
from knowledge_base.api import documents as document_routes
from knowledge_base.api import history as history_routes
from knowledge_base.api import search as search_routes
from knowledge_base.api import system as system_routes
from knowledge_base.api.dependencies import Domains, UpstreamHealth
from knowledge_base.code.engine import CodeEngine, UnknownRepo
from knowledge_base.code.upstream import UpstreamUnavailable
from knowledge_base.docs.graph import GraphUnavailable
from knowledge_base.docs.service import DocumentService
from knowledge_base.docs.store import LearningExists, NoSuchDocument
from knowledge_base.layout import OutsideBoundary
from knowledge_base.vcs import GitError, NoSuchRevision

__all__ = ["UpstreamHealth", "create_app"]

API_PREFIX = "/api"

REFUSALS: tuple[tuple[type[Exception], int], ...] = (
    (OutsideBoundary, 400),
    (LearningExists, 409),
    (NoSuchRevision, 404),
    (NoSuchDocument, 404),
    (UnknownRepo, 404),
    (GraphUnavailable, 503),
    (UpstreamUnavailable, 503),
    (GitError, 500),
)
"""What each way of refusing a request means over HTTP.

Keeping the table here rather than a try/except at every route is what stops the same
refusal from becoming a 400 in one endpoint and a 500 in the next.
"""


def create_app(
    documents: DocumentService,
    code: CodeEngine,
    supervisor: UpstreamHealth | None = None,
    address: Address | None = None,
) -> FastAPI:
    """Build the REST API over domains someone else started."""
    application = FastAPI(
        title="knowledge-base",
        description="内部知识库的 REST API，供网页端使用。",
        version="0.1.0",
    )
    application.state.domains = Domains(
        documents=documents,
        code=code,
        supervisor=supervisor,
        address=address if address is not None else RoutedAddress(),
    )

    for router in (
        search_routes.router,
        document_routes.router,
        history_routes.router,
        code_routes.router,
        system_routes.router,
    ):
        application.include_router(router, prefix=API_PREFIX)

    for failure, status in REFUSALS:
        application.add_exception_handler(failure, _refusal(status))
    return application


def _refusal(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(request: Request, failure: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(failure)})

    return handler
