"""The two paths the service exists to make possible, walked end to end.

Not a unit test of anything: a real HTTP server, a real MCP client, a real knowledge base on
disk, and assertions taken from the file system and from `git log` rather than from anything
the service reported about itself.

The document path runs everywhere. The code path needs codebase-memory-mcp, which is built per
platform and absent from most workstations, so it is marked `upstream_binary` and skipped when
the binary is not installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from conftest import commits, files_in
from knowledge_base.code.process import EXECUTABLE, CbmBinary
from knowledge_base.layout import KnowledgeBaseRoot
from service_harness import served

AUTHOR = "杜宇琦"

SUMMARY = "DataCopyPad 搬运非对齐长度时上游会静默截断"

PITFALL = "在 MC62 上用 DataCopyPad 搬运 int8 时，长度不是 32 字节整数倍会被静默截断"

REPOSITORY = "toolbox"

SOURCE = """\
#include <stdio.h>

int helper(int value) { return value + 1; }

int entry_point(int value) { return helper(value); }

int main(void) { return entry_point(1); }
"""


class TestTheDistillingPath:
    """One agent writes a learning down; another finds it and reads it; git has it."""

    async def test_an_agent_distils_and_a_colleague_finds_it(self, tmp_path: Path) -> None:
        async with served(tmp_path) as address:
            async with Client(f"{address}/mcp") as writer:
                distilled = await writer.call_tool(
                    "distill_learning",
                    {
                        "author": AUTHOR,
                        "folder": "ascendc",
                        "title": "DataCopyPad 的对齐要求",
                        "summary": SUMMARY,
                        "tags": ["ascendc", "mc62"],
                        "observations": [
                            {"category": "pitfall", "content": PITFALL, "tags": ["datacopy"]}
                        ],
                    },
                )
            uri = distilled.data.uri

            # On disk, where a person browsing the repository would find it.
            written = (tmp_path / uri).read_text(encoding="utf-8")
            assert PITFALL in written
            assert uri.startswith("learnings/ascendc/")

            # A second agent, a fresh session, searching in the words of the problem rather
            # than in the words of the title.
            async with Client(f"{address}/mcp") as reader:
                found = await reader.call_tool("search_knowledge", {"query": "静默截断"})
                assert [match.uri for match in found.data.matches] == [uri]
                assert PITFALL in found.data.matches[0].observations[0]

                whole = await reader.call_tool("read_knowledge", {"uri": uri})
                assert whole.data.summary == SUMMARY
                assert whole.data.observations == [f"[pitfall] {PITFALL} #datacopy"]

        # The service has now stopped, which is when the debounced commit is flushed.
        assert files_in(tmp_path, "HEAD") == [uri]
        assert commits(tmp_path)[0].startswith(f"{AUTHOR}|")


@pytest.mark.upstream_binary
class TestTheCodePath:
    """One agent finds a symbol, reads it, and follows who calls it.

    Needs the real binary: every hop is answered by the upstream's graph, and faking it would
    only be testing our own doubles. See README「代码链路的人工验证」for the Ubuntu procedure.
    """

    async def test_an_agent_searches_reads_and_traces_a_symbol(self, tmp_path: Path) -> None:
        if shutil.which(EXECUTABLE) is None:
            pytest.skip(f"{EXECUTABLE} is not installed")

        repository = tmp_path / "codebase" / REPOSITORY
        repository.mkdir(parents=True)
        (repository / "main.c").write_text(SOURCE, encoding="utf-8")

        async with served(tmp_path, binary=CbmBinary(KnowledgeBaseRoot(tmp_path))) as address:
            # What an operator does after cloning a repository into codebase/.
            async with httpx.AsyncClient(base_url=address, timeout=600.0) as operator:
                built = await operator.post(f"/api/code/repos/{REPOSITORY}/index")
                assert built.json()["ok"] is True

            async with Client(f"{address}/mcp") as agent:
                listed = await agent.call_tool("list_repos", {})
                assert [one.name for one in listed.data.repos] == [REPOSITORY]

                found = await agent.call_tool(
                    "search_code", {"query": "entry_point", "repo": REPOSITORY}
                )
                assert "entry_point" in str(found.data.payload)

                source = await agent.call_tool(
                    "read_symbol", {"qualified_name": "entry_point", "repo": REPOSITORY}
                )
                assert "helper" in str(source.data.payload)

                callers = await agent.call_tool(
                    "trace_calls",
                    {"symbol": "helper", "direction": "inbound", "repo": REPOSITORY},
                )
                assert "entry_point" in str(callers.data.payload)
                assert callers.data.caveat is not None
