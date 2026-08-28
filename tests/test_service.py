"""Tests for the document domain as a whole.

This is the surface the MCP tools and the REST API are built on: reads run concurrently,
writes queue up behind one another, changes made outside the service are noticed, and history
reaches git on its own.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from conftest import FakeClock, ManualSleep, commits, files_in
from knowledge_base.docs.notes import Learning, Observation, Relation
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot

QUIET = timedelta(seconds=30)
BETWEEN_COMMITS = timedelta(seconds=5)
PATIENCE = 15.0

OVERVIEW = "knowledge/搬运 API 概览.md"


class Harness:
    """A running document domain, with its clock and its heartbeat under test control."""

    def __init__(
        self,
        root: KnowledgeBaseRoot,
        service: DocumentService,
        clock: FakeClock,
        sleep: ManualSleep,
    ) -> None:
        self.root = root
        self.service = service
        self.clock = clock
        self.sleep = sleep

    async def go_quiet(self) -> None:
        """Let the author fall silent, then let the heartbeat notice."""
        self.clock.advance(QUIET.total_seconds() + 1)
        await self.sleep.tick()

    def write(self, relative: str, text: str) -> None:
        path = self.root.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    async def wait_until_searchable(self, query: str) -> list[str]:
        async with asyncio.timeout(PATIENCE):
            while not (hits := await self.service.search(query)):
                await asyncio.sleep(0.05)
        return sorted({hit.path for hit in hits})


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    root = KnowledgeBaseRoot(tmp_path)
    root.initialize()
    clock, sleep = FakeClock(), ManualSleep()
    service = DocumentService(
        root,
        quiet_period=QUIET,
        commit_interval=BETWEEN_COMMITS,
        clock=clock,
        sleep=sleep,
    )
    running = Harness(root, service, clock, sleep)
    await service.start()
    try:
        yield running
    finally:
        await service.stop()


def a_learning(**kwargs: object) -> Learning:
    return Learning(
        title=str(kwargs.get("title", "DataCopy 的对齐要求")),
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["ascendc"],
        author=str(kwargs.get("author", "dyq")),
        observations=[Observation("pitfall", str(kwargs.get("fact", "非对齐搬运时会读到脏数据")))],
        relations=list(kwargs.get("relations", [])),  # pyright: ignore[reportArgumentType]
    )


class TestDistilling:
    async def test_a_distilled_learning_can_be_searched_for_at_once(self, harness: Harness) -> None:
        path = await harness.service.create_learning("ascendc", a_learning())

        hits = await harness.service.search("脏数据")

        assert sorted({hit.path for hit in hits}) == [path]

    async def test_a_distilled_learning_reaches_git_once_its_author_goes_quiet(
        self, harness: Harness
    ) -> None:
        """Nothing else calls the auto-committer; the service has to keep its own time."""
        path = await harness.service.create_learning("ascendc", a_learning())

        await harness.go_quiet()

        assert commits(harness.root.path) == ["dyq|dyq 沉淀了 1 处改动"]
        assert files_in(harness.root.path, "HEAD") == [path]

    async def test_two_authors_distilling_at_once_each_get_their_own_commit(
        self, harness: Harness
    ) -> None:
        """History is only worth keeping if it says who concluded what."""
        await asyncio.gather(
            harness.service.create_learning("ascendc", a_learning(title="甲", author="dyq")),
            harness.service.create_learning("ascendc", a_learning(title="乙", author="ops")),
        )

        await harness.go_quiet()

        assert commits(harness.root.path) == [
            "ops|ops 沉淀了 1 处改动",
            "dyq|dyq 沉淀了 1 处改动",
        ]


class TestChangesFromOutside:
    async def test_knowledge_written_by_hand_becomes_searchable(self, harness: Harness) -> None:
        """knowledge/ is edited in the web UI and by git pull, never through distillation."""
        harness.write(OVERVIEW, "# 搬运 API 概览\n\n非对齐搬运会读到脏数据。\n")

        assert await harness.wait_until_searchable("脏数据") == [OVERVIEW]

    async def test_a_document_deleted_by_hand_stops_being_found(self, harness: Harness) -> None:
        harness.write(OVERVIEW, "# 搬运 API 概览\n\n非对齐搬运会读到脏数据。\n")
        await harness.wait_until_searchable("脏数据")

        (harness.root.path / OVERVIEW).unlink()

        async with asyncio.timeout(PATIENCE):
            while await harness.service.search("脏数据"):
                await asyncio.sleep(0.05)


class TestExploringLinks:
    async def test_it_follows_a_relation_from_a_learning_to_the_knowledge_it_cites(
        self, harness: Harness
    ) -> None:
        harness.write(OVERVIEW, "---\ntitle: 搬运 API 概览\n---\n\n# 搬运 API 概览\n")
        learning = a_learning(relations=[Relation("relates_to", "搬运 API 概览")])
        path = await harness.service.create_learning("ascendc", learning)
        await harness.service.rebuild()

        neighbourhood = await harness.service.explore_links(path)

        assert [document.path for document in neighbourhood.documents] == [OVERVIEW]


class TestRebuilding:
    async def test_it_reports_progress_while_it_works(self, harness: Harness) -> None:
        for name in ("甲", "乙", "丙"):
            harness.write(f"knowledge/{name}.md", f"# {name}\n")
        reported: list[tuple[int, int]] = []

        await harness.service.rebuild(progress=lambda done, total: reported.append((done, total)))

        assert reported == [(1, 3), (2, 3), (3, 3)]


class TestConcurrency:
    async def test_a_burst_of_distillation_lands_in_full(self, harness: Harness) -> None:
        """Ten agents distilling at once must produce ten learnings, not a lock timeout."""
        paths = await asyncio.gather(
            *(
                harness.service.create_learning("ascendc", a_learning(title=f"经验 {n}"))
                for n in range(10)
            )
        )

        assert sorted(paths) == sorted(f"learnings/ascendc/经验 {n}.md" for n in range(10))
        for path in paths:
            assert (harness.root.path / path).is_file()


class TestEditingByHand:
    """The web UI's write path: people maintain knowledge/, agents may not."""

    async def test_a_document_written_in_the_browser_is_searchable_at_once(
        self, harness: Harness
    ) -> None:
        await harness.service.write_document(OVERVIEW, "# 概览\n\n非对齐会读到脏数据。\n", "dyq")

        assert sorted({hit.path for hit in await harness.service.search("脏数据")}) == [OVERVIEW]

    async def test_it_reaches_git_behind_the_same_debounce_as_a_distillation(
        self, harness: Harness
    ) -> None:
        await harness.service.write_document(OVERVIEW, "# 概览\n", "dyq")

        await harness.go_quiet()

        assert commits(harness.root.path) == ["dyq|dyq 沉淀了 1 处改动"]
        assert files_in(harness.root.path, "HEAD") == [OVERVIEW]

    async def test_it_refuses_to_write_into_the_codebase(self, harness: Harness) -> None:
        from knowledge_base.layout import OutsideDocuments

        with pytest.raises(OutsideDocuments):
            await harness.service.write_document("codebase/mops/README.md", "偷渡", "dyq")


class TestRollingBack:
    async def test_it_restores_a_document_and_appends_a_commit(self, harness: Harness) -> None:
        for text in ("# 概览\n\n旧结论。\n", "# 概览\n\n新结论。\n"):
            await harness.service.write_document(OVERVIEW, text, "dyq")
            await harness.go_quiet()
        first = (await harness.service.history(OVERVIEW))[-1].revision

        await harness.service.restore(OVERVIEW, first, "ops")

        assert (harness.root.path / OVERVIEW).read_text(encoding="utf-8") == "# 概览\n\n旧结论。\n"
        assert len(commits(harness.root.path)) == 3


class TestListing:
    async def test_the_tag_cloud_counts_every_tag_in_use(self, harness: Harness) -> None:
        await harness.service.create_learning("ascendc", a_learning(title="甲"))
        await harness.service.create_learning("ascendc", a_learning(title="乙"))

        assert [(t.tag, t.count) for t in await harness.service.tag_cloud()] == [("ascendc", 2)]

    async def test_the_tree_lists_documents_from_both_directories(self, harness: Harness) -> None:
        harness.write(OVERVIEW, "# 概览\n")
        await harness.service.create_learning("ascendc", a_learning())
        await harness.service.rebuild()

        assert [d.path for d in await harness.service.documents()] == [
            OVERVIEW,
            "learnings/ascendc/DataCopy 的对齐要求.md",
        ]


@pytest.mark.parametrize("folder", ["../knowledge", "/etc"])
async def test_it_still_refuses_to_write_outside_learnings(harness: Harness, folder: str) -> None:
    """Queuing a write must not lose the boundary the write would have been refused at."""
    from knowledge_base.layout import OutsideLearnings

    with pytest.raises(OutsideLearnings):
        await harness.service.create_learning(folder, a_learning())
