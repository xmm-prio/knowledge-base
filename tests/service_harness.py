"""The whole service, assembled the way the operator's process is.

Two ways in, because the tests need two different things. `assembled` runs the composed
application's lifespan and speaks to it over an in-process transport, which is enough for
every question about routing and degradation. `served` puts a real HTTP server in front of it,
for the one path that has to be walked exactly as an agent walks it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn

from api_harness import ADVERTISED_HOST, ADVERTISED_PORT
from knowledge_base.address import Address, FixedAddress
from knowledge_base.code.supervisor import Binary
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.server import Service
from upstream_doubles import FakeBinary

STARTUP_PATIENCE = 30.0

NO_FRONTEND = "no-frontend-built-here"
"""A directory that does not exist, so a test says nothing about the developer's checkout."""

BUNDLE = b"console.log('kb')\n"
"""Written as bytes: a built asset must reach the browser exactly as the build left it."""


@dataclass
class Running:
    """A started service and a client onto it."""

    service: Service
    binary: Binary
    client: httpx.AsyncClient

    @property
    def root(self) -> Path:
        return self.service.root.path


@asynccontextmanager
async def assembled(
    path: Path, binary: Binary | None = None, frontend: Path | None = None
) -> AsyncIterator[Running]:
    """The composed application with its lifespan run, reachable without a socket."""
    upstream = binary if binary is not None else FakeBinary()
    service = Service(
        KnowledgeBaseRoot(path),
        binary=upstream,
        frontend=frontend if frontend is not None else path / NO_FRONTEND,
        address=FixedAddress(ADVERTISED_HOST, ADVERTISED_PORT),
    )
    application = service.application
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://kb.internal") as client:
            yield Running(service=service, binary=upstream, client=client)


@asynccontextmanager
async def served(
    path: Path,
    binary: Binary | None = None,
    frontend: Path | None = None,
    address: Address | None = None,
) -> AsyncIterator[str]:
    """The same assembly behind a real HTTP server, yielding the address it listens on.

    What it *listens* on and what it *advertises* are two different things, which is the whole
    point of the resolver: the socket is a loopback port picked by the kernel, and the address
    handed to a member is stated -- or, in the release gate, resolved for real.

    Leaving this block shuts the service down the way systemd does, which is when the
    debounced commit is flushed -- so history can be asserted on afterwards.
    """
    service = Service(
        KnowledgeBaseRoot(path),
        binary=binary if binary is not None else FakeBinary(),
        frontend=frontend if frontend is not None else path / NO_FRONTEND,
        address=address if address is not None else FixedAddress(ADVERTISED_HOST, ADVERTISED_PORT),
    )
    server = uvicorn.Server(
        uvicorn.Config(service.application, host="127.0.0.1", port=0, log_config=None)
    )
    running = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(STARTUP_PATIENCE):
            while not server.started:
                await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        await running


def build_frontend(directory: Path, shell: str = "<!doctype html><title>kb</title>") -> Path:
    """What `npm run build` leaves behind, reduced to what the server cares about."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(shell, encoding="utf-8")
    assets = directory / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "app.js").write_bytes(BUNDLE)
    return directory


__all__ = ["Running", "assembled", "build_frontend", "served"]
