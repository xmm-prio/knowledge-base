"""The composition root: the one place that decides what a running process contains.

Every other module was built to be handed its collaborators, and none of them starts anything.
Here they are put together in the order they depend on each other, given one lifecycle, and
joined into a single ASGI application with three faces on it:

- `/api` for the browser, from `api.create_app`
- `/mcp` for the agents, from `mcp.create_mcp_app`
- everything else for the built single-page app, when there is one

Two properties are the reason this stage exists at all. The MCP application carries its own
lifespan -- mounting an ASGI app does not run it, and an unrun Streamable HTTP session manager
refuses every handshake -- so the host lifespan enters it explicitly. And the code domain's
binary is built per platform and may simply be absent, which must cost the code domain and
nothing else: documents, search and history are the larger half of the service.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from knowledge_base.address import Address, RoutedAddress
from knowledge_base.api import create_app
from knowledge_base.code.engine import CodeEngine
from knowledge_base.code.process import CbmBinary
from knowledge_base.code.supervisor import Binary, Supervisor
from knowledge_base.code.upstream import UpstreamUnavailable
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.mcp import create_mcp_app
from knowledge_base.mcp.progress import HEARTBEAT

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
"""Where an agent's Streamable HTTP client connects. Matched before the single-page app."""

FRONTEND_DIST = "frontend/dist"
"""The built web UI, relative to the source checkout the service was installed from."""

INDEX_FILE = "index.html"

UNAVAILABLE = "代码域不可用：上游 codebase-memory-mcp 没有启动"


def default_frontend() -> Path:
    """Where the built single-page app sits in the checkout this package came from."""
    return Path(__file__).resolve().parents[2] / FRONTEND_DIST


class SupervisedUpstream:
    """The supervised binary as the rest of the process must see it.

    Always present, sometimes unavailable. A supervisor that would not start is kept rather
    than dropped, so every question put to the code domain is refused with a reason and its
    health reads false -- which is exactly the shape the REST layer already reports as
    `ok=false`, and the shape the MCP layer already turns into a tool error.
    """

    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Bring the upstream up, reporting rather than raising when it will not come."""
        try:
            self._supervisor.start()
        except Exception as failure:  # noqa: BLE001 - a missing binary is a degraded mode
            logger.warning("Code domain degraded: the upstream did not start: %s", failure)
            return False
        self._running = True
        return True

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        if not self._running:
            raise UpstreamUnavailable(UNAVAILABLE)
        return self._supervisor.call_tool(tool, arguments)

    def check_health(self) -> bool:
        if not self._running:
            return False
        try:
            return self._supervisor.check_health()
        except UpstreamUnavailable as gone:
            logger.warning("Upstream health could not be established: %s", gone)
            return False

    def stop(self) -> None:
        """Close the session and take the shared coordination daemon with it (ADR-0007)."""
        if not self._running:
            return
        self._running = False
        self._supervisor.stop()


class SinglePageApp(StaticFiles):
    """The built web UI, with client-side routes answered by the shell.

    A browser reloading on a path only the SPA knows about asks the server for it, so anything
    that is not a built file is the SPA's own routing and must get `index.html` rather than a
    404. It is mounted last, after `/api` and `/mcp`, so it can never swallow them.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as missing:
            if missing.status_code != 404:
                raise
        return await super().get_response(INDEX_FILE, scope)


class Gateway:
    """Several applications behind one address, each keeping the path it was asked for.

    Not Starlette's `Mount`, which strips the prefix it matched and only ever matches paths
    strictly deeper than it: an application mounted at `/mcp` answers `/mcp/` and not `/mcp`,
    and `/mcp` is the address every agent is handed. Here a request goes whole to the first
    application whose prefix it falls under, and everything left over -- which is most of it,
    since the web UI owns its own routing -- goes to the last one.
    """

    def __init__(self, endpoints: Sequence[tuple[str, ASGIApp]], rest: ASGIApp) -> None:
        self._endpoints = tuple(endpoints)
        self._rest = rest

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        for prefix, application in self._endpoints:
            if path == prefix or path.startswith(f"{prefix}/"):
                await application(scope, receive, send)
                return
        await self._rest(scope, receive, send)


class Service:
    """One knowledge base, running: two domains behind two faces, with one lifecycle."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        binary: Binary | None = None,
        frontend: Path | None = None,
        heartbeat: timedelta = HEARTBEAT,
        address: Address | None = None,
    ) -> None:
        self.root = root
        self.upstream = SupervisedUpstream(Supervisor(binary or CbmBinary(root)))
        self.documents = DocumentService(root)
        self.code = CodeEngine(root, self.upstream)
        self.address = address if address is not None else RoutedAddress()
        self._mcp = create_mcp_app(
            root, self.documents, self.code, heartbeat=heartbeat, path=MCP_PATH
        )
        self.application = self._compose(frontend if frontend is not None else default_frontend())

    async def start(self) -> None:
        """Bring the knowledge base up, in the order the parts depend on each other.

        The search index lives in memory and holds nothing the files do not (ADR-0006), so
        the last step is reading the knowledge base into it. Until that has happened a search
        answers nothing, which is worse than a slow start.
        """
        self.root.initialize()
        self.upstream.start()
        await self.documents.start()
        logger.info("Indexed %d documents", await self.documents.rebuild())

    async def stop(self) -> None:
        """Take it down again, newest first, leaving nothing written out of history."""
        await self.documents.stop()
        self.upstream.stop()

    def _compose(self, frontend: Path) -> Starlette:
        """One application out of three, with the MCP lifespan run by the host's."""
        api = create_app(self.documents, self.code, supervisor=self.upstream, address=self.address)
        if frontend.is_dir():
            api.mount("/", SinglePageApp(frontend), name="frontend")
        else:
            logger.warning(
                "The web UI is not built at %s; serving the API and the MCP endpoint only",
                frontend,
            )
        gateway = Gateway([(MCP_PATH, self._mcp)], rest=api)
        # Mounting at the root leaves every path untouched; the outer application exists
        # only so that the whole assembly has one lifespan.
        return Starlette(lifespan=self._lifespan, routes=[Mount("/", app=gateway)])

    @asynccontextmanager
    async def _lifespan(self, _host: Starlette) -> AsyncIterator[None]:
        """Start the domains, then the mounted application that has a lifespan of its own.

        Starlette runs the lifespan of the application it was given and of no other, so the
        MCP session manager would never be entered if it were not entered here by hand.
        """
        await self.start()
        try:
            async with AsyncExitStack() as running:
                await running.enter_async_context(self._mcp.router.lifespan_context(self._mcp))
                yield
        finally:
            await self.stop()


@asynccontextmanager
async def document_domain(root: KnowledgeBaseRoot) -> AsyncIterator[DocumentService]:
    """The document side alone, started and stopped around one piece of work.

    A command that only touches documents has no business starting the code upstream: it costs
    a subprocess, and its coordination daemon allows one cache directory per account, so
    starting it needlessly is enough to lock someone else out (ADR-0007).

    Reading the knowledge base in is part of starting it, exactly as it is for `Service`: the
    search index is in memory and holds nothing until the files are read, so a domain that has
    not been rebuilt is one that answers every question with nothing.
    """
    root.initialize()
    documents = DocumentService(root)
    await documents.start()
    try:
        await documents.rebuild()
        yield documents
    finally:
        # Stopping is what flushes the debounced commit, so it is never optional.
        await documents.stop()


@dataclass(frozen=True)
class CodeSide:
    """The code domain as anyone assembling it needs it: what to ask, and whether it is there.

    The two travel together everywhere -- the REST layer takes the engine and the health probe
    as separate arguments, and a caller that has one always wants the other.
    """

    engine: CodeEngine
    upstream: SupervisedUpstream


@asynccontextmanager
async def code_domain(
    root: KnowledgeBaseRoot, binary: Binary | None = None
) -> AsyncIterator[CodeSide]:
    """The code side alone, started and stopped around one piece of work.

    The mirror of the above: indexing a repository does not need the document graph, whose
    upstream costs several seconds of migrations and model loading to bring up.

    One conversation, not the pool the served process keeps: a command has one caller, and a
    second upstream process would be a second few seconds of startup for nobody.
    """
    root.initialize()
    upstream = SupervisedUpstream(Supervisor(binary or CbmBinary(root), conversations=1))
    upstream.start()
    try:
        yield CodeSide(CodeEngine(root, upstream), upstream)
    finally:
        upstream.stop()
