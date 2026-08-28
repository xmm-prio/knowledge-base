"""Tests for the MCP surface as a whole: what an agent can see, and how much it costs to see."""

import re

from mcp_harness import Library, library

__all__ = ["library"]

EXPECTED_TOOLS = {
    "search_knowledge",
    "read_knowledge",
    "explore_links",
    "distill_learning",
    "list_repos",
    "get_architecture",
    "search_code",
    "read_symbol",
    "trace_calls",
    "query_code_graph",
}

DESCRIPTION_BUDGET = 60
"""Han characters per tool description. Ten tools sit in every member's context, and context
bloat is the first caveat opencode's own documentation raises about MCP."""


async def test_only_the_first_party_tools_are_exposed(library: Library) -> None:
    """Neither upstream's own tools reach an agent, whatever they are called. See ADR-0002."""
    tools = await library.client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_every_tool_says_what_it_is_for_briefly(library: Library) -> None:
    tools = await library.client.list_tools()

    too_long = {
        tool.name: len(re.findall(r"[\u4e00-\u9fff]", tool.description or ""))
        for tool in tools
        if len(re.findall(r"[\u4e00-\u9fff]", tool.description or "")) > DESCRIPTION_BUDGET
    }
    assert too_long == {}


async def test_a_tool_that_writes_is_the_only_one_not_marked_read_only(
    library: Library,
) -> None:
    tools = await library.client.list_tools()

    writers = {
        tool.name for tool in tools if not (tool.annotations and tool.annotations.read_only_hint)
    }
    assert writers == {"distill_learning"}
