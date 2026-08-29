"""The last thing run before a release, against the binary that will actually be deployed.

Everything else in this suite proves the gateway behaves against a double that answers the way
we believe the upstream answers. That belief is the thing being checked here: the pool holding
several real child processes, the real index deciding what "indexed" means, the real qualified
names surviving the round trip from a search result back into a read, and a real reconnect
after the shared daemon is pulled out from under a live session.

The whole module is marked `upstream_binary`, so `-m upstream_binary` runs the gate and nothing
else. Everything that drives the binary skips with its reason when the binary is not installed
or when another daemon on this account holds the cache; the address check needs no binary and
runs anywhere, because a machine with no address to hand out is a release problem too. See
README「发布前的真实上游门禁」for the one command that runs the lot.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from conftest import require_upstream
from knowledge_base.address import advertised_for
from knowledge_base.code.process import CbmBinary
from knowledge_base.layout import KnowledgeBaseRoot
from service_harness import served

pytestmark = pytest.mark.upstream_binary

REPOSITORY = "gate"

INDEXING_PATIENCE = 600.0
"""Seconds. A first index of even a small repository starts a daemon and builds a graph."""

READERS = 20
"""The concurrency the acceptance criteria state: ten clients, twenty reads in flight."""

SOURCE = """\
#include <stdio.h>

int helper(int value) { return value + 1; }

int entry_point(int value) { return helper(value); }

int main(void) { return entry_point(1); }
"""


def prepared(path: Path) -> CbmBinary:
    """A knowledge base with one small repository in it, and the real binary to index it."""
    root = KnowledgeBaseRoot(path)
    root.initialize()
    binary = require_upstream(root)
    repository = root.codebase_dir / REPOSITORY
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "main.c").write_text(SOURCE, encoding="utf-8")
    return binary


async def indexed(client: httpx.AsyncClient) -> None:
    built = await client.post(f"/api/code/repos/{REPOSITORY}/index")
    assert built.json()["ok"] is True, built.text


class TestTheRealPool:
    async def test_twenty_reads_at_once_each_get_their_own_answer(self, tmp_path: Path) -> None:
        """The failure this guards against is silent: two callers on one pair of pipes read
        each other's replies, and both answers look plausible."""
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                await indexed(client)

                asked = ["helper", "entry_point", "main"] * READERS
                answers = await asyncio.gather(
                    *(
                        client.get("/api/code/search", params={"q": one, "repo": REPOSITORY})
                        for one in asked[:READERS]
                    )
                )

                for wanted, answer in zip(asked, answers, strict=False):
                    body = answer.json()
                    assert body["ok"] is True, body
                    names = [one["display_qn"] for one in body["payload"]["matches"]]
                    assert any(wanted in name for name in names), (wanted, names)

    async def test_a_reconnect_mid_flight_does_not_cost_the_caller_their_answer(
        self, tmp_path: Path
    ) -> None:
        """Stopping the shared daemon is the upstream's own way of pulling the rug out."""
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                await indexed(client)
                assert (await client.get("/api/code/repos")).json()["repos"][0]["indexed"] is True

                binary.run("daemon", "stop")

                again = await client.get(
                    "/api/code/search", params={"q": "helper", "repo": REPOSITORY}
                )
                assert again.json()["ok"] is True, again.text

    async def test_indexing_cut_off_by_a_reconnect_is_reported_not_replayed(
        self, tmp_path: Path
    ) -> None:
        """Half an index written twice is worse than an index that says it did not finish."""
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                await indexed(client)
                binary.run("daemon", "stop")

                cut_off = await client.post(f"/api/code/repos/{REPOSITORY}/index")

                # Either it never reached a dead session, or it was refused with the reason.
                body = cut_off.json()
                assert body["ok"] is True or "not sent again" in str(body["payload"]), body
                await indexed(client)


class TestWhatTheRealIndexSays:
    async def test_indexed_means_the_upstream_can_answer_about_it_now(self, tmp_path: Path) -> None:
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                before = (await client.get("/api/code/repos")).json()["repos"]
                assert [one["indexed"] for one in before] == [False]

                await indexed(client)

                after = (await client.get("/api/code/repos")).json()["repos"]
                assert [one["indexed"] for one in after] == [True]

    async def test_a_name_from_a_search_reads_back_as_source(self, tmp_path: Path) -> None:
        """The whole point of keeping two names: the short one is shown, the long one works."""
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                await indexed(client)

                found = await client.get(
                    "/api/code/search", params={"q": "entry_point", "repo": REPOSITORY}
                )
                (first,) = [
                    one
                    for one in found.json()["payload"]["matches"]
                    if "entry_point" in one["display_qn"]
                ][:1]
                assert first["display_qn"].startswith(REPOSITORY)

                source = await client.get(
                    "/api/code/symbol",
                    params={"name": first["canonical_qn"], "repo": REPOSITORY},
                )
                assert source.json()["ok"] is True, source.text
                assert "helper" in str(source.json()["payload"])

    async def test_a_traced_chain_comes_back_as_edges_between_real_symbols(
        self, tmp_path: Path
    ) -> None:
        binary = prepared(tmp_path)
        async with served(tmp_path, binary=binary) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                await indexed(client)

                traced = await client.get(
                    "/api/code/calls",
                    params={"symbol": "helper", "direction": "inbound", "repo": REPOSITORY},
                )
                chain = traced.json()["payload"]
                assert traced.json()["caveat"]
                assert any("entry_point" in edge["caller"] for edge in chain["edges"]), chain


class TestWhatThisMachineHandsOut:
    """The address half of the gate: resolved on the deployment machine, not on a double."""

    def test_this_machine_has_an_address_worth_giving_a_colleague(self) -> None:
        """A member copies the MCP snippet into their own config. It must not say localhost."""
        reachable = advertised_for("0.0.0.0", port=8080).advertised()

        assert not reachable.host.startswith("127.")
        assert reachable.url("/mcp").endswith(f"{reachable.host}:8080/mcp")

    async def test_the_service_reports_that_same_address(self, tmp_path: Path) -> None:
        binary = prepared(tmp_path)
        wanted = advertised_for("0.0.0.0", port=8080)
        async with served(tmp_path, binary=binary, address=wanted) as address:
            async with httpx.AsyncClient(base_url=address, timeout=INDEXING_PATIENCE) as client:
                mcp = (await client.get("/api/system/status")).json()["mcp"]

                assert mcp["error"] is None
                assert mcp["url"] == wanted.advertised().url("/mcp")
