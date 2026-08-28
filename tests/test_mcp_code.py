"""Tests for the code-side MCP tools.

The upstream binary's payloads are passed through untouched -- their shape was never
documented, so inventing structure for them would only mislead -- and every answer drawn from
the call graph carries the warning that it may be missing edges.
"""

import asyncio
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from mcp_harness import Library, StubUpstream, library, running

__all__ = ["library"]

ARCHITECTURE = {"languages": ["c"], "entry_points": [{"name": "main"}]}


@pytest.fixture
def mops(library: Library) -> Library:
    library.place_repo("mops")
    return library


class TestListRepos:
    async def test_it_lists_what_operators_placed_under_codebase(self, mops: Library) -> None:
        listing = await mops.call("list_repos")

        assert [(repo.name, repo.path) for repo in listing.repos] == [("mops", "codebase/mops")]

    async def test_a_repo_the_upstream_has_not_indexed_yet_says_so(self, mops: Library) -> None:
        """On disk and searchable are different states, and an agent has to know which it has."""
        listing = await mops.call("list_repos")

        assert [repo.indexed for repo in listing.repos] == [False]


class TestAsking:
    async def test_an_architecture_overview_comes_back_as_the_upstream_wrote_it(
        self, mops: Library
    ) -> None:
        mops.upstream.answers["get_architecture"] = ARCHITECTURE

        answer = await mops.call("get_architecture", repo="mops")

        assert answer.payload == ARCHITECTURE

    async def test_searching_by_symbol_is_the_default_and_text_search_is_asked_for(
        self, mops: Library
    ) -> None:
        await mops.call("search_code", query="DataCopy.*", repo="mops")
        await mops.call("search_code", query="DataCopy.*", repo="mops", mode="text")

        assert mops.upstream.arguments_for("search_graph") == [
            {"name_pattern": "DataCopy.*", "project": "mops"}
        ]
        assert mops.upstream.arguments_for("search_code") == [
            {"query": "DataCopy.*", "project": "mops"}
        ]

    async def test_reading_a_symbol_asks_for_it_by_qualified_name(self, mops: Library) -> None:
        await mops.call("read_symbol", qualified_name="src.copy.DataCopyPad")

        assert mops.upstream.arguments_for("get_code_snippet") == [
            {"qualified_name": "src.copy.DataCopyPad"}
        ]

    async def test_tracing_answers_who_calls_this_unless_told_otherwise(
        self, mops: Library
    ) -> None:
        await mops.call("trace_calls", symbol="DataCopyPad")

        assert mops.upstream.arguments_for("trace_path") == [
            {"function_name": "DataCopyPad", "direction": "inbound", "depth": 3}
        ]

    async def test_a_cypher_query_reaches_the_upstream_untouched(self, mops: Library) -> None:
        """The one passthrough: rewriting the query would defeat its purpose."""
        cypher = "MATCH (f:Function) RETURN f.name LIMIT 1"

        await mops.call("query_code_graph", cypher=cypher)

        assert mops.upstream.arguments_for("query_graph") == [{"query": cypher}]


class TestHonesty:
    async def test_an_answer_off_the_call_graph_admits_it_may_be_missing_edges(
        self, mops: Library
    ) -> None:
        answer = await mops.call("trace_calls", symbol="DataCopyPad")

        assert answer.caveat is not None

    async def test_reading_source_carries_no_such_warning(self, mops: Library) -> None:
        answer = await mops.call("read_symbol", qualified_name="src.copy.DataCopyPad")

        assert answer.caveat is None


class TestStayingUp:
    """opencode never reconnects, so nothing here may reach the connection as an exception."""

    async def test_asking_about_a_repo_that_is_not_there_points_at_list_repos(
        self, mops: Library
    ) -> None:
        with pytest.raises(ToolError, match="list_repos"):
            await mops.call("get_architecture", repo="nope")

    async def test_an_upstream_that_refuses_leaves_the_connection_usable(
        self, mops: Library
    ) -> None:
        mops.upstream.answers["get_architecture"] = RuntimeError("binary is not running")

        with pytest.raises(ToolError):
            await mops.call("get_architecture", repo="mops")

        assert await mops.call("list_repos") is not None


class SlowUpstream(StubUpstream):
    """A binary that takes long enough to cross an agent's tool-call timeout."""

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        time.sleep(0.3)
        return super().call_tool(tool, arguments)


async def test_a_slow_answer_keeps_reporting_that_it_is_still_working(tmp_path: Path) -> None:
    """opencode cuts a tool call off after thirty seconds of silence, but resets that clock on
    every progress report. Indexing a large repository is well past thirty seconds."""
    async with running(tmp_path, SlowUpstream(), heartbeat=timedelta(seconds=0.05)) as library:
        library.place_repo("mops")

        await library.call("get_architecture", repo="mops")

        assert len(library.progress) >= 2


async def test_a_slow_answer_does_not_block_the_other_tools(tmp_path: Path) -> None:
    """The code domain is synchronous; running it inline would stall every other agent."""
    async with running(tmp_path, SlowUpstream()) as library:
        library.place_repo("mops")

        started = time.monotonic()
        await asyncio.gather(*(library.call("get_architecture", repo="mops") for _ in range(4)))

        assert time.monotonic() - started < 1.0
