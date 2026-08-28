"""Tests for the document-side MCP tools.

Everything here goes through an MCP client, because that is what an agent has: the tools are
reached by name, with a JSON payload, and the answer is judged by what lands in the agent's
context rather than by what the gateway computed on the way there.
"""

import re

import pytest
from fastmcp.exceptions import ToolError

from knowledge_base.docs.notes import Learning, Observation, Relation
from mcp_harness import Library, library

__all__ = ["library"]

ALIGNMENT = Learning(
    title="DataCopy 的对齐要求",
    summary="非 32B 对齐的尾块会读到脏数据",
    tags=["ascendc", "datacopy"],
    author="dyq",
    observations=[
        Observation("pitfall", "blockLen 非 32B 对齐时尾块会读到脏数据", ["ascendc"]),
        Observation("verified", "改用 DataCopyPad 后实测通过"),
    ],
)


class TestSearchKnowledge:
    async def test_a_match_carries_the_observation_that_was_hit_verbatim(
        self, library: Library
    ) -> None:
        """The point of observation-level retrieval: the answer itself, not the file it is in."""
        await library.documents.create_learning("ascendc", ALIGNMENT)

        found = await library.call("search_knowledge", query="脏数据")

        assert [match.observations for match in found.matches] == [
            ["blockLen 非 32B 对齐时尾块会读到脏数据"]
        ]

    async def test_a_match_says_where_it_is_and_what_it_concluded(self, library: Library) -> None:
        await library.documents.create_learning("ascendc", ALIGNMENT)

        found = await library.call("search_knowledge", query="脏数据")

        assert (found.matches[0].uri, found.matches[0].title, found.matches[0].summary) == (
            "learnings/ascendc/DataCopy 的对齐要求.md",
            "DataCopy 的对齐要求",
            "非 32B 对齐的尾块会读到脏数据",
        )

    async def test_no_prose_of_the_document_comes_back(self, library: Library) -> None:
        """Progressive disclosure: the body is what read_knowledge is for."""
        library.write(
            "knowledge/搬运 API 概览.md",
            "# 搬运 API 概览\n\n## 背景\n\n这段正文很长，不应该出现在检索结果里。\n\n"
            "- [pitfall] 非对齐搬运会读到脏数据\n",
        )
        await library.documents.rebuild()

        found = await library.call("search_knowledge", query="脏数据")

        assert "这段正文很长" not in str(found)

    async def test_a_match_carries_the_outline_so_an_agent_can_aim_its_next_read(
        self, library: Library
    ) -> None:
        library.write(
            "knowledge/搬运 API 概览.md",
            "# 搬运 API 概览\n\n## 背景\n\n正文。\n\n"
            "## 对齐\n\n- [pitfall] 非对齐搬运会读到脏数据\n",
        )
        await library.documents.rebuild()

        found = await library.call("search_knowledge", query="脏数据")

        assert found.matches[0].outline == ["搬运 API 概览", "背景", "对齐"]

    async def test_a_document_hit_and_its_observation_hits_are_one_match(
        self, library: Library
    ) -> None:
        """One document, one entry in the agent's context, however many rows the index has."""
        await library.documents.create_learning("ascendc", ALIGNMENT)

        found = await library.call("search_knowledge", query="对齐")

        assert len(found.matches) == 1
        assert len(found.matches[0].observations) == 1

    async def test_it_can_be_narrowed_to_documents_carrying_every_named_tag(
        self, library: Library
    ) -> None:
        library.write(
            "knowledge/概览.md",
            "---\ntags: [mdc]\n---\n\n# 概览\n\n- [note] 非对齐搬运会读到脏数据\n",
        )
        await library.documents.create_learning("ascendc", ALIGNMENT)
        await library.documents.rebuild()

        found = await library.call("search_knowledge", query="脏数据", tags=["ascendc"])

        assert [match.uri for match in found.matches] == ["learnings/ascendc/DataCopy 的对齐要求.md"]

    async def test_it_can_be_narrowed_to_one_category_of_observation(
        self, library: Library
    ) -> None:
        """"What has bitten people" is a different question from "what has been verified"."""
        both = Learning(
            title="尾块处理",
            summary="尾块要单独处理",
            author="dyq",
            observations=[
                Observation("pitfall", "尾块会读到脏数据"),
                Observation("verified", "尾块补齐后实测通过"),
            ],
        )
        await library.documents.create_learning("ascendc", both)

        found = await library.call("search_knowledge", query="尾块", category="verified")

        assert [match.observations for match in found.matches] == [["尾块补齐后实测通过"]]

    async def test_nothing_found_is_an_empty_answer_rather_than_an_error(
        self, library: Library
    ) -> None:
        found = await library.call("search_knowledge", query="没有人写过这个")

        assert found.matches == []


OVERVIEW = "knowledge/搬运 API 概览.md"
OVERVIEW_TEXT = (
    "# 搬运 API 概览\n\n"
    "## 背景\n\n搬运 API 有三代实现。\n\n"
    "## 对齐\n\n非对齐的尾块要用 DataCopyPad。\n\n"
    "- [pitfall] 非对齐搬运会读到脏数据\n"
)


SEARCH_BUDGET = 500
"""Han characters a whole search answer may cost. The acceptance criterion is that finding
somebody else's conclusion costs an agent a few hundred tokens, not a few thousand."""


async def test_a_search_over_a_library_costs_an_agent_a_few_hundred_tokens(
    library: Library,
) -> None:
    """Progressive disclosure is only real if the first layer is cheap."""
    for n in range(20):
        library.write(
            f"knowledge/长文档 {n}.md",
            f"# 长文档 {n}\n\n## 背景\n\n" + "非对齐搬运的细节说明。" * 200 + "\n\n"
            "- [pitfall] 非对齐搬运会读到脏数据\n",
        )
    await library.documents.rebuild()

    found = await library.call("search_knowledge", query="脏数据")

    assert len(found.matches) == 8
    assert len(re.findall(r"[\u4e00-\u9fff]", str(found))) <= SEARCH_BUDGET


class TestReadKnowledge:
    async def test_reading_a_document_gives_its_prose_and_its_observations(
        self, library: Library
    ) -> None:
        library.write(OVERVIEW, OVERVIEW_TEXT)
        await library.documents.rebuild()

        content = await library.call("read_knowledge", uri=OVERVIEW)

        assert "搬运 API 有三代实现。" in content.content
        assert content.observations == ["[pitfall] 非对齐搬运会读到脏数据"]

    async def test_reading_one_section_leaves_the_rest_out(self, library: Library) -> None:
        """The second layer of disclosure has a second layer of its own."""
        library.write(OVERVIEW, OVERVIEW_TEXT)
        await library.documents.rebuild()

        content = await library.call("read_knowledge", uri=OVERVIEW, section="对齐")

        assert "DataCopyPad" in content.content
        assert "三代实现" not in content.content

    async def test_a_document_lists_the_sections_that_can_be_asked_for(
        self, library: Library
    ) -> None:
        library.write(OVERVIEW, OVERVIEW_TEXT)
        await library.documents.rebuild()

        content = await library.call("read_knowledge", uri=OVERVIEW)

        assert content.sections == ["搬运 API 概览", "背景", "对齐"]

    async def test_asking_for_a_section_that_is_not_there_says_which_ones_are(
        self, library: Library
    ) -> None:
        library.write(OVERVIEW, OVERVIEW_TEXT)
        await library.documents.rebuild()

        with pytest.raises(ToolError, match="对齐"):
            await library.call("read_knowledge", uri=OVERVIEW, section="没有这一节")

    async def test_reading_a_document_that_does_not_exist_is_an_error_not_a_crash(
        self, library: Library
    ) -> None:
        with pytest.raises(ToolError):
            await library.call("read_knowledge", uri="knowledge/不存在.md")


class TestExploreLinks:
    async def test_it_follows_a_relation_to_the_knowledge_a_learning_cites(
        self, library: Library
    ) -> None:
        library.write(OVERVIEW, "---\ntitle: 搬运 API 概览\n---\n\n# 搬运 API 概览\n")
        cites = Learning(
            title="DataCopy 的对齐要求",
            summary="非 32B 对齐的尾块会读到脏数据",
            author="dyq",
            observations=[Observation("pitfall", "尾块会读到脏数据")],
            relations=[Relation("relates_to", "搬运 API 概览")],
        )
        uri = await library.documents.create_learning("ascendc", cites)
        await library.documents.rebuild()

        graph = await library.call("explore_links", uri=uri)

        assert [document.uri for document in graph.documents] == [OVERVIEW]
        assert [(link.type, link.target) for link in graph.links] == [("relates_to", OVERVIEW)]

    async def test_exploring_a_document_that_does_not_exist_is_an_error_not_a_crash(
        self, library: Library
    ) -> None:
        with pytest.raises(ToolError):
            await library.call("explore_links", uri="learnings/无人/不存在.md")


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("all", ["knowledge/概览.md", "learnings/ascendc/DataCopy 的对齐要求.md"]),
        ("knowledge", ["knowledge/概览.md"]),
        ("learnings", ["learnings/ascendc/DataCopy 的对齐要求.md"]),
    ],
)
async def test_search_can_be_narrowed_to_one_kind_of_document(
    library: Library, scope: str, expected: list[str]
) -> None:
    """Curated knowledge and distilled experience are asked for at different moments."""
    library.write("knowledge/概览.md", "# 概览\n\n- [note] 非对齐搬运会读到脏数据\n")
    await library.documents.create_learning("ascendc", ALIGNMENT)
    await library.documents.rebuild()

    found = await library.call("search_knowledge", query="脏数据", scope=scope)

    assert sorted(match.uri for match in found.matches) == expected
