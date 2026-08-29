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

from knowledge_base.code.upstream import UpstreamUnavailable
from mcp_harness import Library, StubUpstream, library, running

__all__ = ["library"]

ARCHITECTURE = {"languages": ["c"], "entry_points": [{"name": "main"}]}


@pytest.fixture
def mops(library: Library) -> Library:
    library.place_repo("mops")
    return library


@pytest.fixture
def project(library: Library) -> str:
    """What the upstream calls the repository these tests ask about."""
    return library.place_repo("mops")


class TestListRepos:
    async def test_it_lists_what_operators_placed_under_codebase(self, mops: Library) -> None:
        listing = await mops.call("list_repos")

        assert [(repo.name, repo.path) for repo in listing.repos] == [("mops", "codebase/mops")]

    async def test_a_repo_the_upstream_has_not_indexed_yet_says_so(self, library: Library) -> None:
        """On disk and searchable are different states, and an agent has to know which it has."""
        library.place_repo("fresh", indexed=False)

        listing = await library.call("list_repos")

        assert [repo.indexed for repo in listing.repos] == [False]


class TestAsking:
    async def test_an_architecture_overview_comes_back_as_the_upstream_wrote_it(
        self, mops: Library
    ) -> None:
        mops.upstream.answers["get_architecture"] = ARCHITECTURE

        answer = await mops.call("get_architecture", repo="mops")

        assert answer.payload == ARCHITECTURE

    async def test_searching_by_symbol_is_the_default_and_text_search_is_asked_for(
        self, library: Library, project: str
    ) -> None:
        await library.call("search_code", query="DataCopyPad", repo="mops")
        await library.call("search_code", query="DataCopyPad", repo="mops", mode="text")

        (graph,) = library.upstream.arguments_for("search_graph")
        (grep,) = library.upstream.arguments_for("search_code")
        assert (graph["name_pattern"], graph["project"]) == ("DataCopyPad", project)
        assert (grep["pattern"], grep["project"]) == ("DataCopyPad", project)

    async def test_reading_a_symbol_asks_for_it_by_qualified_name(
        self, library: Library, project: str
    ) -> None:
        await library.call("read_symbol", qualified_name="src.copy.DataCopyPad")

        assert library.upstream.arguments_for("get_code_snippet") == [
            {"qualified_name": "src.copy.DataCopyPad", "project": project}
        ]

    async def test_tracing_answers_who_calls_this_unless_told_otherwise(
        self, library: Library, project: str
    ) -> None:
        await library.call("trace_calls", symbol="DataCopyPad")

        (asked,) = library.upstream.arguments_for("trace_path")
        assert (asked["function_name"], asked["direction"], asked["depth"]) == (
            "DataCopyPad",
            "inbound",
            3,
        )

    async def test_a_cypher_query_reaches_the_upstream_untouched(
        self, library: Library, project: str
    ) -> None:
        """The one passthrough: rewriting the query would defeat its purpose."""
        cypher = "MATCH (f:Function) RETURN f.name LIMIT 1"

        await library.call("query_code_graph", cypher=cypher, repo="mops")

        assert library.upstream.arguments_for("query_graph") == [
            {"query": cypher, "project": project}
        ]


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

    async def test_a_missing_binary_is_not_reported_as_a_bad_question(self, mops: Library) -> None:
        """An agent that thinks it mistyped will keep retyping. It has to be told to stop."""
        mops.upstream.answers["search_graph"] = UpstreamUnavailable("the binary is gone")

        with pytest.raises(ToolError, match="上游"):
            await mops.call("search_code", query="Run")

    async def test_a_bad_pattern_says_so_and_can_be_quoted(self, mops: Library) -> None:
        with pytest.raises(ToolError, match="正则"):
            await mops.call("search_code", query="Run(", mode="regex")


class TestNamesAnAgentAsksWith:
    async def test_a_search_result_carries_the_name_to_ask_with(self, mops: Library) -> None:
        mops.upstream.answers["search_graph"] = {
            "results": [{"qualified_name": "_srv_kb_mops_src.copy.Run", "project": "mops"}]
        }

        answer = await mops.call("search_code", query="Run", repo="mops")

        (one,) = answer.payload["matches"]
        assert one["canonical_qn"] == "_srv_kb_mops_src.copy.Run"
        assert one["display_qn"] == "mops.copy.Run"

    async def test_the_short_name_is_refused_where_the_canonical_one_belongs(
        self, mops: Library
    ) -> None:
        """Otherwise the shortening we do for readability silently breaks the next call."""
        with pytest.raises(ToolError, match="canonical_qn"):
            await mops.call("read_symbol", qualified_name="mops.copy.Run#a1b2c3")


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
