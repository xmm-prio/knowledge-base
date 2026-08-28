"""Tests for the document domain facade.

This is the seam the MCP tools and the REST API both sit on: everything that reads or writes
a Markdown file in the knowledge base goes through here.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from conftest import FakeClock, commits, files_in
from knowledge_base.docs.notes import Learning, Observation
from knowledge_base.docs.store import DocumentStore, LearningExists, NoSuchLearning
from knowledge_base.layout import KnowledgeBaseRoot, OutsideLearnings

QUIET = timedelta(seconds=30)


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    root = KnowledgeBaseRoot(tmp_path)
    root.initialize()
    return DocumentStore(root, quiet_period=QUIET)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def found(store: DocumentStore, query: str) -> list[str]:
    return sorted({hit.path for hit in store.search(query)})


class TestRebuild:
    def test_it_indexes_markdown_under_knowledge_and_learnings(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n搬运前必须检查地址对齐。\n")
        write(tmp_path, "learnings/ascendc/对齐.md", "# 对齐\n\n非对齐搬运时会读到脏数据。\n")

        store.rebuild()

        assert found(store, "对齐") == ["knowledge/搬运.md", "learnings/ascendc/对齐.md"]
        assert found(store, "脏数据") == ["learnings/ascendc/对齐.md"]

    def test_it_leaves_the_codebase_alone(self, store: DocumentStore, tmp_path: Path) -> None:
        """codebase/ holds source, not documents, and can be enormous."""
        write(tmp_path, "codebase/proj/README.md", "# 搬运说明\n\n地址对齐要求。\n")

        store.rebuild()

        assert found(store, "对齐") == []

    def test_it_ignores_files_that_are_not_markdown(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/data.json", '{"对齐": true}')

        store.rebuild()

        assert found(store, "对齐") == []

    def test_running_it_twice_does_not_duplicate_hits(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n地址对齐。\n")

        store.rebuild()
        store.rebuild()

        assert len(store.search("对齐")) == 1

    def test_it_reports_progress_so_a_long_rebuild_can_be_watched(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        """A rebuild outlives an agent's tool-call timeout unless it keeps reporting."""
        for name in ("甲", "乙", "丙"):
            write(tmp_path, f"knowledge/{name}.md", f"# {name}\n")
        reported: list[tuple[int, int]] = []

        store.rebuild(progress=lambda done, total: reported.append((done, total)))

        assert reported == [(1, 3), (2, 3), (3, 3)]


class TestSynchronize:
    """knowledge/ is edited by hand and by git, not only through this service."""

    def test_it_indexes_a_document_that_appeared_on_disk(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n非对齐搬运会读到脏数据。\n")

        store.synchronize("knowledge/搬运.md")

        assert found(store, "脏数据") == ["knowledge/搬运.md"]

    def test_it_reindexes_a_document_that_changed_on_disk(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n非对齐搬运会读到脏数据。\n")
        store.synchronize("knowledge/搬运.md")

        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n改用双缓冲后正确。\n")
        store.synchronize("knowledge/搬运.md")

        assert found(store, "脏数据") == []
        assert found(store, "双缓冲") == ["knowledge/搬运.md"]

    def test_it_forgets_a_document_that_left_the_disk(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n\n非对齐搬运会读到脏数据。\n")
        store.synchronize("knowledge/搬运.md")

        (tmp_path / "knowledge/搬运.md").unlink()
        store.synchronize("knowledge/搬运.md")

        assert found(store, "脏数据") == []

    def test_it_leaves_paths_outside_the_indexed_directories_alone(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "codebase/proj/README.md", "# 搬运说明\n\n地址对齐要求。\n")

        store.synchronize("codebase/proj/README.md")

        assert found(store, "对齐") == []


def a_learning(**kwargs) -> Learning:
    return Learning(
        title=kwargs.pop("title", "DataCopy 的对齐要求"),
        summary=kwargs.pop("summary", "非 32B 对齐的尾块会读到脏数据"),
        tags=kwargs.pop("tags", ["ascendc"]),
        author=kwargs.pop("author", "dyq"),
        observations=kwargs.pop(
            "observations", [Observation("pitfall", "非对齐搬运时会读到脏数据")]
        ),
        relations=kwargs.pop("relations", []),
    )


class TestCreateLearning:
    def test_it_writes_the_learning_where_the_agent_asked(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        path = store.create_learning("ascendc", a_learning())

        assert path == "learnings/ascendc/DataCopy 的对齐要求.md"
        assert (tmp_path / path).is_file()

    def test_the_new_learning_is_searchable_immediately(self, store: DocumentStore) -> None:
        """An agent that distills something and then looks for it must find it."""
        store.create_learning("ascendc", a_learning())

        assert found(store, "脏数据") == ["learnings/ascendc/DataCopy 的对齐要求.md"]

    def test_it_refuses_to_write_outside_learnings(self, store: DocumentStore) -> None:
        with pytest.raises(OutsideLearnings):
            store.create_learning("../knowledge", a_learning())

    def test_it_refuses_to_overwrite_an_existing_learning(self, store: DocumentStore) -> None:
        """Overwriting silently would lose someone's conclusion; append or revise instead."""
        store.create_learning("ascendc", a_learning())

        with pytest.raises(LearningExists):
            store.create_learning("ascendc", a_learning())


class TestAppendToLearning:
    def test_it_adds_observations_and_keeps_the_existing_ones(self, store: DocumentStore) -> None:
        path = store.create_learning("ascendc", a_learning())

        store.append_to_learning(path, "ops", [Observation("verified", "改用 DataCopyPad 后正确")])

        assert [o.content for o in store.read(path).observations] == [
            "非对齐搬运时会读到脏数据",
            "改用 DataCopyPad 后正确",
        ]

    def test_the_appended_observation_is_searchable(self, store: DocumentStore) -> None:
        path = store.create_learning("ascendc", a_learning())

        store.append_to_learning(path, "ops", [Observation("verified", "双缓冲深度设为 2")])

        assert found(store, "双缓冲") == [path]

    def test_it_refuses_a_learning_that_does_not_exist(self, store: DocumentStore) -> None:
        with pytest.raises(NoSuchLearning):
            store.append_to_learning("learnings/nope.md", "ops", [Observation("note", "x")])


class TestReviseLearning:
    def test_it_replaces_a_rotten_observation_in_place(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        """The old conclusion leaves the file entirely -- its history lives in git."""
        path = store.create_learning("ascendc", a_learning())

        store.revise_learning(
            path,
            "ops",
            replaces="非对齐搬运时会读到脏数据",
            replacement=Observation("verified", "驱动 6.0 起尾块已由硬件补齐"),
        )

        assert [o.content for o in store.read(path).observations] == ["驱动 6.0 起尾块已由硬件补齐"]
        assert "非对齐搬运时会读到脏数据" not in (tmp_path / path).read_text(encoding="utf-8")
        assert found(store, "硬件补齐") == [path]

    def test_it_refuses_when_the_observation_is_not_there(self, store: DocumentStore) -> None:
        path = store.create_learning("ascendc", a_learning())

        with pytest.raises(NoSuchLearning):
            store.revise_learning(
                path, "ops", replaces="从来没写过这句", replacement=Observation("note", "x")
            )


class TestHistory:
    """Writes must actually reach git, or the version mechanism is decoration."""

    def test_a_distilled_learning_is_committed_once_its_author_goes_quiet(
        self, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        root = KnowledgeBaseRoot(tmp_path)
        root.initialize()
        store = DocumentStore(root, quiet_period=QUIET, clock=clock)
        path = store.create_learning("ascendc", a_learning())

        assert commits(tmp_path) == []

        clock.advance(31)
        store.commit_if_quiet()

        assert commits(tmp_path) == ["dyq|dyq 沉淀了 1 处改动"]
        assert files_in(tmp_path, "HEAD") == [path]


class TestDeleteLearning:
    def test_it_removes_the_file_and_the_index_entry(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        path = store.create_learning("ascendc", a_learning())

        store.delete_learning(path, "dyq")

        assert not (tmp_path / path).exists()
        assert found(store, "脏数据") == []

    def test_it_refuses_to_delete_outside_learnings(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        write(tmp_path, "knowledge/搬运.md", "# UB 搬运\n")

        with pytest.raises(OutsideLearnings):
            store.delete_learning("knowledge/搬运.md", "dyq")

        assert (tmp_path / "knowledge/搬运.md").exists()
