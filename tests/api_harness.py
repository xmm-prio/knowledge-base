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

QUIET = timedelta(seconds=30)
BETWEEN_COMMITS = timedelta(seconds=5)
PATIENCE = 15.0

ADVERTISED_HOST = "kb.internal"
ADVERTISED_PORT = 8080
"""What the service says it is reachable on. Stated rather than resolved, because the address
of whatever machine runs the tests is not a thing to assert against."""


class FakeUpstream:
    """The supervised binary, answering with canned payloads."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.failing: set[str] = set()
        self.raising: dict[str, Exception] = {}
        """Failures of a stated kind, for tests about how a failure is classified."""

        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool, arguments))
        if (stated := self.raising.get(tool)) is not None:
            raise stated
        if tool in self.failing:
            raise RuntimeError(f"{tool} refused")
        return self.answers.get(tool, {})

    def arguments_for(self, tool: str) -> list[dict[str, object]]:
        return [arguments for name, arguments in self.calls if name == tool]


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

    def place_repo(self, name: str) -> None:
        (self.root.codebase_dir / name / "src").mkdir(parents=True)
        (self.root.codebase_dir / name / "src" / "main.c").write_text("int main(void){return 0;}\n")

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
