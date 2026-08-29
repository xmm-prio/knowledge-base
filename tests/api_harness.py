"""A running REST API, for tests that speak to it over HTTP.

The document domain underneath is real -- files, index and git all work -- because the API's
job is to expose it faithfully. The code domain's binary only exists on the deployment
target, so its upstream is faked exactly as the code domain's own tests fake it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx

from conftest import FakeClock, ManualSleep
from knowledge_base.address import Address, FixedAddress, NoRouteOutward, Reachable
from knowledge_base.api import create_app
from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot
from upstream_doubles import StubUpstream, derived_name

QUIET = timedelta(seconds=30)
BETWEEN_COMMITS = timedelta(seconds=5)
PATIENCE = 15.0

ADVERTISED_HOST = "kb.internal"
ADVERTISED_PORT = 8080
"""What the service says it is reachable on. Stated rather than resolved, because the address
of whatever machine runs the tests is not a thing to assert against."""


FakeUpstream = StubUpstream
"""The name this harness has always used for the code domain's double."""


class Unreachable:
    """A machine with no address worth handing out: no default route, or IPv6 only."""

    def advertised(self) -> Reachable:
        raise NoRouteOutward(
            "找不到可对外提供服务的 IPv4 地址：这台机器没有默认路由，"
            "或者只有 IPv6。请用 --host 显式指定组员能连上的地址。"
        )


class FakeSupervisor:
    """Whatever the operator's process assembly hands the API as a health probe."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    def check_health(self) -> bool:
        return self.healthy


class ApiHarness:
    """The API, the domains behind it, and the clock they keep."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        documents: DocumentService,
        upstream: FakeUpstream,
        supervisor: FakeSupervisor,
        client: httpx.AsyncClient,
        clock: FakeClock,
        sleep: ManualSleep,
    ) -> None:
        self.root = root
        self.documents = documents
        self.upstream = upstream
        self.supervisor = supervisor
        self.client = client
        self.clock = clock
        self.sleep = sleep

    def write(self, relative: str, text: str) -> None:
        """Put a document on disk the way a git pull or an operator would."""
        path = self.root.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def place_repo(self, name: str, indexed: bool = True) -> str:
        """Put a repository on disk, and hand back what the upstream would call it."""
        location = self.root.codebase_dir / name
        (location / "src").mkdir(parents=True)
        (location / "src" / "main.c").write_text("int main(void){return 0;}\n")
        return self.upstream.indexes(location) if indexed else derived_name(location)

    async def go_quiet(self) -> None:
        """Let the author fall silent, then let the heartbeat notice."""
        self.clock.advance(QUIET.total_seconds() + 1)
        await self.sleep.tick()

    async def indexed(self, relative: str) -> None:
        """Wait until a document written on disk has reached the index."""
        async with asyncio.timeout(PATIENCE):
            while not any(
                document.path == relative for document in await self.documents.documents()
            ):
                await asyncio.sleep(0.05)


@asynccontextmanager
async def running_api(root_path: Path, address: Address | None = None) -> AsyncIterator[ApiHarness]:
    """The whole thing, started and torn down again."""
    root = KnowledgeBaseRoot(root_path)
    root.initialize()
    clock, sleep = FakeClock(), ManualSleep()
    documents = DocumentService(
        root,
        quiet_period=QUIET,
        commit_interval=BETWEEN_COMMITS,
        clock=clock,
        sleep=sleep,
    )
    upstream = FakeUpstream()
    supervisor = FakeSupervisor()
    application = create_app(
        documents,
        CodeEngine(root, upstream),
        supervisor=supervisor,
        address=address if address is not None else FixedAddress(ADVERTISED_HOST, ADVERTISED_PORT),
    )

    await documents.start()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://kb.internal") as client:
        try:
            yield ApiHarness(root, documents, upstream, supervisor, client, clock, sleep)
        finally:
            await documents.stop()
