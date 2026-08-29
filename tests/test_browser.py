"""What a member sees in a browser.

Everything else in this suite asks the service questions in Python. These tests read the
screen instead, because "the page said the repository is not indexed" is a claim about the
page, and no amount of asserting on JSON can settle it.
"""

from __future__ import annotations

import re
from pathlib import Path

from api_harness import ADVERTISED_HOST, ADVERTISED_PORT
from browser_harness import Browsing, browsing
from upstream_doubles import FakeBinary, tool_result

ADVERTISED = f"http://{ADVERTISED_HOST}:{ADVERTISED_PORT}/mcp"
"""What `served()` states this service is reachable on, whatever port the socket got."""

LEARNING = """\
---
title: 对齐要求
summary: DataCopy 的搬运长度必须按 32 字节对齐
tags: [ascendc]
---

## Observations
- [pitfall] 未对齐的搬运长度会让上游静默截断 #ascendc
"""


class TestTheAppLoads:
    async def test_the_shell_reaches_the_browser(self, tmp_path: Path) -> None:
        """The whole seam in one assertion: a built bundle, a real server, a real browser."""
        async with browsing(tmp_path) as open_on:
            await open_on.page.wait_for_selector("nav")

            assert await open_on.page.locator("nav").inner_text() != ""

    async def test_it_can_reach_the_service_behind_it(self, tmp_path: Path) -> None:
        """A page that renders but cannot call `/api` looks fine and is useless."""
        (tmp_path / "learnings").mkdir(exist_ok=True)
        (tmp_path / "learnings" / "对齐要求.md").write_text(LEARNING, encoding="utf-8")

        async with browsing(tmp_path, route="/system") as open_on:
            await open_on.page.get_by_text("文档域").wait_for()

            assert "1" in await open_on.page.inner_text("body")

    async def test_the_address_on_the_page_is_the_one_the_service_hands_out(
        self, tmp_path: Path
    ) -> None:
        """Not the host the browser used to get here: the snippet gets pasted elsewhere."""
        async with browsing(tmp_path, route="/system") as open_on:
            await open_on.page.get_by_text(ADVERTISED).first.wait_for()

            assert open_on.address not in await open_on.page.inner_text("body")

    async def test_the_code_page_lists_what_is_on_disk(self, tmp_path: Path) -> None:
        (tmp_path / "codebase" / "mops").mkdir(parents=True)
        binary = FakeBinary({"list_projects": tool_result({"projects": []})})

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await open_on.page.get_by_text("mops").first.wait_for()

            assert "codebase/mops" in await open_on.page.inner_text("body")


def with_repo(path: Path, name: str = "mops") -> None:
    (path / "codebase" / name / "src").mkdir(parents=True)
    (path / "codebase" / name / "src" / "main.c").write_text("int main(void){return 0;}\n")


LISTED = tool_result({"projects": [{"name": "mops"}]})

FOUND = tool_result(
    {"results": [{"qualified_name": "_srv_kb_mops_src.copy.DataCopyPad", "project": "mops"}]}
)

TRACED = tool_result(
    {
        "paths": [[{"qn": "_srv_kb_mops_src.kernel.Main"}, {"qn": "_srv_kb_mops_src.copy.Run"}]],
        "edges": [{"caller": "_srv_kb_mops_src.kernel.Main"}],
    }
)


class TestWhatTheIndexStateSays:
    async def test_a_repository_the_upstream_can_search_reads_as_indexed(
        self, tmp_path: Path
    ) -> None:
        with_repo(tmp_path)
        binary = FakeBinary({"list_projects": LISTED, "search_graph": tool_result({})})

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await open_on.page.get_by_text("已索引").first.wait_for()

    async def test_one_it_remembers_but_cannot_search_does_not(self, tmp_path: Path) -> None:
        """Told it is indexed, a member spends twenty minutes not believing the search box."""
        with_repo(tmp_path)
        binary = FakeBinary(
            {
                "list_projects": LISTED,
                "search_graph": {"error": {"code": -32000, "message": "no graph for project"}},
            }
        )

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await open_on.page.get_by_text("未索引").first.wait_for()


SYMBOL_BOX = re.compile("^符号名")
CANONICAL_BOX = re.compile("^canonical_qn")
TRACE_BOX = re.compile("^起点符号")


async def search_for(open_on: Browsing, text: str, regex: bool = False) -> None:
    """Do what a member does: pick the symbol tab, type, and press the button."""
    await open_on.page.get_by_role("button", name="符号搜索", exact=True).click()
    if regex:
        await open_on.page.get_by_role("button", name="正则", exact=True).click()
    await open_on.page.get_by_label(SYMBOL_BOX).fill(text)
    await open_on.page.get_by_role("button", name="搜索", exact=True).click()


async def trace_from(open_on: Browsing, canonical: str) -> None:
    await open_on.page.get_by_role("button", name="调用链", exact=True).click()
    await open_on.page.get_by_label(TRACE_BOX).fill(canonical)
    await open_on.page.get_by_role("button", name="追踪", exact=True).click()


class TestWhatAFailureSays:
    async def test_a_mistyped_pattern_is_not_blamed_on_the_upstream(self, tmp_path: Path) -> None:
        """The old page said 上游没有应答 to a bracket the member had left open."""
        with_repo(tmp_path)

        async with browsing(tmp_path, binary=FakeBinary(), route="/code") as open_on:
            await search_for(open_on, "DataCopy(", regex=True)

            await open_on.page.get_by_text("这次查询本身有问题").wait_for()
            assert "上游没有应答" not in await open_on.page.inner_text("body")

    async def test_a_failure_can_be_quoted_to_an_operator(self, tmp_path: Path) -> None:
        with_repo(tmp_path)
        refusing = FakeBinary(
            {"search_graph": {"error": {"code": -32000, "message": "no such project"}}}
        )

        async with browsing(tmp_path, binary=refusing, route="/code") as open_on:
            await search_for(open_on, "DataCopyPad")

            await open_on.page.get_by_text("诊断").wait_for()


class TestFollowingAResult:
    async def test_a_hit_is_shown_short_and_carries_the_long_name(self, tmp_path: Path) -> None:
        with_repo(tmp_path)
        binary = FakeBinary({"list_projects": LISTED, "search_graph": FOUND})

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await search_for(open_on, "DataCopyPad")

            await open_on.page.get_by_text("mops.copy.DataCopyPad").wait_for()

    async def test_clicking_a_hit_reads_its_source_under_the_canonical_name(
        self, tmp_path: Path
    ) -> None:
        """The short name is for reading. Handing it back would break the very call it makes."""
        with_repo(tmp_path)
        binary = FakeBinary(
            {
                "list_projects": LISTED,
                "search_graph": FOUND,
                "get_code_snippet": tool_result({"code": "void DataCopyPad(void) {}"}),
            }
        )

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await search_for(open_on, "DataCopyPad")
            await open_on.page.get_by_role("button", name="读源码", exact=True).click()

            asked = await open_on.page.get_by_label(CANONICAL_BOX).input_value()
            assert asked == "_srv_kb_mops_src.copy.DataCopyPad"

    async def test_a_call_chain_is_read_as_a_chain_not_as_json(self, tmp_path: Path) -> None:
        with_repo(tmp_path)
        binary = FakeBinary({"list_projects": LISTED, "trace_path": TRACED})

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await trace_from(open_on, "_srv_kb_mops_src.copy.Run")

            await open_on.page.get_by_text("kernel.Main").first.wait_for()
            assert "第 1 跳" in await open_on.page.inner_text("body")

    async def test_what_could_not_be_resolved_is_said_rather_than_dropped(
        self, tmp_path: Path
    ) -> None:
        """An empty chain that quietly dropped a relation reads as proof of no callers."""
        with_repo(tmp_path)
        binary = FakeBinary({"list_projects": LISTED, "trace_path": TRACED})

        async with browsing(tmp_path, binary=binary, route="/code") as open_on:
            await trace_from(open_on, "_srv_kb_mops_src.copy.Run")

            await open_on.page.get_by_text("无法唯一确定").wait_for()
