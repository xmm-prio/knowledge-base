"""Tests for distillation: the one way an agent writes to the knowledge base.

Which of the four things a call does is decided by the arguments alone, so every branch and
every argument combination that cannot mean anything is pinned down here.
"""

import pytest
from fastmcp.exceptions import ToolError

from mcp_harness import Library, library

__all__ = ["library"]

ALIGNMENT = "learnings/ascendc/DataCopy 的对齐要求.md"

A_FACT = {"category": "pitfall", "content": "blockLen 非 32B 对齐时尾块会读到脏数据"}
ANOTHER_FACT = {"category": "verified", "content": "改用 DataCopyPad 后实测通过"}


async def distill(library: Library, **arguments: object) -> object:
    return await library.call("distill_learning", author="dyq", **arguments)


async def a_learning(library: Library) -> str:
    result = await distill(
        library,
        folder="ascendc",
        title="DataCopy 的对齐要求",
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["ascendc"],
        observations=[A_FACT],
    )
    return result.uri  # pyright: ignore[reportAttributeAccessIssue]


class TestCreating:
    async def test_a_learning_with_no_target_is_written_as_a_new_document(
        self, library: Library
    ) -> None:
        uri = await a_learning(library)

        assert uri == ALIGNMENT
        assert (library.root.path / ALIGNMENT).is_file()

    async def test_it_reports_which_of_the_four_things_it_did(self, library: Library) -> None:
        result = await distill(
            library,
            folder="ascendc",
            title="DataCopy 的对齐要求",
            summary="非 32B 对齐的尾块会读到脏数据",
            observations=[A_FACT],
        )

        assert result.mode == "新建"  # pyright: ignore[reportAttributeAccessIssue]

    async def test_a_new_learning_is_attributed_to_the_agent_that_distilled_it(
        self, library: Library
    ) -> None:
        """History is only worth keeping if it says who concluded what."""
        await a_learning(library)

        assert "author: dyq" in library.text_of(ALIGNMENT)

    async def test_a_new_learning_can_be_searched_for_at_once(self, library: Library) -> None:
        await a_learning(library)

        found = await library.call("search_knowledge", query="脏数据")

        assert [match.uri for match in found.matches] == [ALIGNMENT]

    async def test_distilling_over_an_existing_learning_is_refused(self, library: Library) -> None:
        """Two agents concluding about the same thing must not overwrite each other."""
        await a_learning(library)

        with pytest.raises(ToolError, match="已经"):
            await a_learning(library)


class TestAppending:
    async def test_a_target_and_observations_add_to_what_is_already_there(
        self, library: Library
    ) -> None:
        await a_learning(library)

        result = await distill(library, target=ALIGNMENT, observations=[ANOTHER_FACT])

        assert result.mode == "追加"  # pyright: ignore[reportAttributeAccessIssue]
        content = await library.call("read_knowledge", uri=ALIGNMENT)
        assert content.observations == [
            "[pitfall] blockLen 非 32B 对齐时尾块会读到脏数据",
            "[verified] 改用 DataCopyPad 后实测通过",
        ]


class TestRevising:
    async def test_a_target_and_a_quoted_observation_overwrite_that_observation(
        self, library: Library
    ) -> None:
        await a_learning(library)

        result = await distill(
            library,
            target=ALIGNMENT,
            replaces=A_FACT["content"],
            observations=[{"category": "verified", "content": "0.11 起尾块已经补齐，不再脏"}],
        )

        assert result.mode == "修订"  # pyright: ignore[reportAttributeAccessIssue]
        content = await library.call("read_knowledge", uri=ALIGNMENT)
        assert content.observations == ["[verified] 0.11 起尾块已经补齐，不再脏"]

    async def test_quoting_an_observation_nobody_wrote_is_refused(self, library: Library) -> None:
        await a_learning(library)

        with pytest.raises(ToolError):
            await distill(
                library,
                target=ALIGNMENT,
                replaces="从来没有人这样写过",
                observations=[ANOTHER_FACT],
            )


class TestDeleting:
    async def test_deleting_removes_the_learning(self, library: Library) -> None:
        await a_learning(library)

        result = await distill(library, target=ALIGNMENT, delete=True)

        assert result.mode == "删除"  # pyright: ignore[reportAttributeAccessIssue]
        assert not (library.root.path / ALIGNMENT).exists()

    async def test_a_deleted_learning_stops_being_found(self, library: Library) -> None:
        await a_learning(library)

        await distill(library, target=ALIGNMENT, delete=True)

        found = await library.call("search_knowledge", query="脏数据")
        assert found.matches == []


class TestArgumentsThatCannotMeanAnything:
    """A write tool that guesses is worse than one that refuses."""

    async def test_creating_without_a_summary_is_refused(self, library: Library) -> None:
        """The summary is the first layer of disclosure; a learning without one is invisible."""
        with pytest.raises(ToolError, match="summary"):
            await distill(library, folder="ascendc", title="无摘要", observations=[A_FACT])

    async def test_creating_without_a_folder_is_refused(self, library: Library) -> None:
        with pytest.raises(ToolError, match="folder"):
            await distill(library, title="无目录", summary="一句话", observations=[A_FACT])

    async def test_creating_without_observations_is_refused(self, library: Library) -> None:
        with pytest.raises(ToolError, match="observations"):
            await distill(library, folder="ascendc", title="空经验", summary="一句话")

    async def test_quoting_an_observation_without_a_target_is_refused(
        self, library: Library
    ) -> None:
        """Nothing can be revised in a document that is being created."""
        with pytest.raises(ToolError, match="target"):
            await distill(
                library,
                folder="ascendc",
                title="新建",
                summary="一句话",
                replaces="某句话",
                observations=[A_FACT],
            )

    async def test_appending_while_also_naming_a_new_document_is_refused(
        self, library: Library
    ) -> None:
        """title and folder say "create"; target says "add to that one". Both is a mistake."""
        await a_learning(library)

        with pytest.raises(ToolError, match="title"):
            await distill(
                library, target=ALIGNMENT, title="另一个标题", observations=[ANOTHER_FACT]
            )

    async def test_appending_nothing_is_refused(self, library: Library) -> None:
        await a_learning(library)

        with pytest.raises(ToolError, match="observations"):
            await distill(library, target=ALIGNMENT)

    async def test_revising_with_more_than_one_conclusion_is_refused(
        self, library: Library
    ) -> None:
        await a_learning(library)

        with pytest.raises(ToolError, match="一条"):
            await distill(
                library,
                target=ALIGNMENT,
                replaces=A_FACT["content"],
                observations=[A_FACT, ANOTHER_FACT],
            )

    async def test_deleting_without_saying_what_is_refused(self, library: Library) -> None:
        with pytest.raises(ToolError, match="target"):
            await distill(library, delete=True)

    async def test_deleting_while_also_writing_something_is_refused(self, library: Library) -> None:
        await a_learning(library)

        with pytest.raises(ToolError):
            await distill(library, target=ALIGNMENT, delete=True, observations=[ANOTHER_FACT])

    async def test_writing_anywhere_but_learnings_is_refused(self, library: Library) -> None:
        """The write boundary is the reason knowledge/ can be trusted."""
        library.write("knowledge/概览.md", "# 概览\n")

        with pytest.raises(ToolError):
            await distill(library, target="knowledge/概览.md", observations=[A_FACT])

    async def test_a_learning_that_is_not_there_is_refused(self, library: Library) -> None:
        with pytest.raises(ToolError):
            await distill(library, target="learnings/无人/不存在.md", observations=[A_FACT])
