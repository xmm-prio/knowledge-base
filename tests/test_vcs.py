"""Tests for debounced auto-commit.

Committing on every write would bury the history in noise -- one commit per observation an
agent distills. Debouncing is what makes git usable as the version mechanism.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from conftest import FakeClock, commits, files_in
from knowledge_base.vcs import AutoCommitter, NoSuchRevision, Repository

QUIET = timedelta(seconds=30)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path)
    repository.ensure()
    return repository


def write(repo: Repository, committer: AutoCommitter, author: str, name: str) -> None:
    path = repo.path / name
    path.write_text("经验", encoding="utf-8")
    committer.record(author, path)


def test_a_write_is_not_committed_straight_away(repo: Repository) -> None:
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=FakeClock())

    write(repo, committer, "dyq", "a.md")
    committer.flush_due()

    assert commits(repo.path) == []


def test_a_write_is_committed_once_the_quiet_period_passes(repo: Repository) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    write(repo, committer, "dyq", "a.md")

    clock.advance(31)
    committer.flush_due()

    assert commits(repo.path) == ["dyq|dyq 沉淀了 1 处改动"]


def test_writes_by_one_author_in_a_row_become_a_single_commit(repo: Repository) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    for name in ("a.md", "b.md", "c.md"):
        write(repo, committer, "dyq", name)
        clock.advance(5)
        committer.flush_due()

    clock.advance(31)
    committer.flush_due()

    assert commits(repo.path) == ["dyq|dyq 沉淀了 3 处改动"]
    assert files_in(repo.path, "HEAD") == ["a.md", "b.md", "c.md"]


def test_a_second_author_does_not_get_merged_into_the_first_ones_commit(
    repo: Repository,
) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    write(repo, committer, "dyq", "a.md")

    clock.advance(5)
    write(repo, committer, "ops", "b.md")

    clock.advance(31)
    committer.flush_due()

    assert commits(repo.path) == ["ops|ops 沉淀了 1 处改动", "dyq|dyq 沉淀了 1 处改动"]
    assert files_in(repo.path, "HEAD") == ["b.md"]
    assert files_in(repo.path, "HEAD~1") == ["a.md"]


def test_rewriting_one_file_counts_as_one_change(repo: Repository) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    for _ in range(3):
        write(repo, committer, "dyq", "a.md")

    clock.advance(31)
    committer.flush_due()

    assert commits(repo.path) == ["dyq|dyq 沉淀了 1 处改动"]


def test_nothing_pending_makes_no_empty_commit(repo: Repository) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)

    clock.advance(99)
    committer.flush_due()

    assert commits(repo.path) == []


def test_a_deliberate_change_gets_its_own_commit_and_its_own_message(repo: Repository) -> None:
    """A rollback is not ambient editing: it must be in history the moment it happens."""
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    path = repo.path / "a.md"
    path.write_text("旧结论", encoding="utf-8")

    assert committer.commit_alone("dyq", path, "dyq 回滚了 a.md") is True
    assert commits(repo.path) == ["dyq|dyq 回滚了 a.md"]


def test_a_deliberate_change_does_not_swallow_another_authors_pending_writes(
    repo: Repository,
) -> None:
    clock = FakeClock()
    committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
    write(repo, committer, "ops", "b.md")

    rolled_back = repo.path / "a.md"
    rolled_back.write_text("旧结论", encoding="utf-8")
    committer.commit_alone("dyq", rolled_back, "dyq 回滚了 a.md")

    assert commits(repo.path) == ["dyq|dyq 回滚了 a.md", "ops|ops 沉淀了 1 处改动"]
    assert files_in(repo.path, "HEAD") == ["a.md"]
    assert files_in(repo.path, "HEAD~1") == ["b.md"]


class TestHistory:
    """The history page reads git, because git is the only record of when anything changed."""

    def test_it_reports_every_commit_newest_first(self, repo: Repository) -> None:
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        for author, name in (("dyq", "甲.md"), ("ops", "乙.md")):
            write(repo, committer, author, name)
            clock.advance(31)
            committer.flush_due()

        revisions = repo.log()

        assert [(r.author, r.message) for r in revisions] == [
            ("ops", "ops 沉淀了 1 处改动"),
            ("dyq", "dyq 沉淀了 1 处改动"),
        ]

    def test_a_revision_carries_a_sha_and_a_timestamp(self, repo: Repository) -> None:
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        write(repo, committer, "dyq", "甲.md")
        clock.advance(31)
        committer.flush_due()

        revision = repo.log()[0]

        assert len(revision.revision) == 40
        assert revision.at.startswith("20")

    def test_it_can_be_narrowed_to_one_document_with_a_chinese_name(self, repo: Repository) -> None:
        """git octal-escapes non-ASCII paths unless told otherwise, and every title is Chinese."""
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        for name in ("对齐要求.md", "双缓冲.md"):
            write(repo, committer, "dyq", name)
            clock.advance(31)
            committer.flush_due()

        revisions = repo.log("对齐要求.md")

        assert len(revisions) == 1
        assert repo.paths_in(revisions[0].revision) == ["对齐要求.md"]

    def test_it_stops_at_the_limit_it_was_given(self, repo: Repository) -> None:
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        for index in range(5):
            write(repo, committer, "dyq", f"{index}.md")
            clock.advance(31)
            committer.flush_due()

        assert len(repo.log(limit=2)) == 2

    def test_a_document_that_was_never_committed_has_no_history(self, repo: Repository) -> None:
        assert repo.log("从未提交.md") == []


class TestReadingOneRevision:
    @pytest.fixture
    def written_twice(self, repo: Repository) -> list[str]:
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        for text in ("旧结论", "新结论"):
            (repo.path / "对齐要求.md").write_text(text, encoding="utf-8")
            committer.record("dyq", repo.path / "对齐要求.md")
            clock.advance(31)
            committer.flush_due()
        return [revision.revision for revision in repo.log("对齐要求.md")]

    def test_it_reads_a_document_as_it_was_at_a_revision(
        self, repo: Repository, written_twice: list[str]
    ) -> None:
        newest, oldest = written_twice

        assert repo.file_at(oldest, "对齐要求.md") == "旧结论"
        assert repo.file_at(newest, "对齐要求.md") == "新结论"

    def test_it_refuses_a_revision_that_is_not_a_commit_id(self, repo: Repository) -> None:
        """Anything but a hex object name could be read as a git option by the process below."""
        with pytest.raises(NoSuchRevision):
            repo.file_at("--upload-pack=touch", "对齐要求.md")

    def test_it_refuses_a_document_that_did_not_exist_at_that_revision(
        self, repo: Repository, written_twice: list[str]
    ) -> None:
        with pytest.raises(NoSuchRevision):
            repo.file_at(written_twice[0], "从未存在.md")


class TestTimestamps:
    """Timestamps come from git, never from frontmatter, so there is one truth. See ADR-0003."""

    def test_a_document_is_created_at_its_first_commit_and_updated_at_its_last(
        self, repo: Repository
    ) -> None:
        clock = FakeClock()
        committer = AutoCommitter(repo, quiet_period=QUIET, clock=clock)
        for text in ("旧结论", "新结论"):
            (repo.path / "对齐要求.md").write_text(text, encoding="utf-8")
            committer.record("dyq", repo.path / "对齐要求.md")
            clock.advance(31)
            committer.flush_due()

        created, updated = repo.timestamps("对齐要求.md")
        revisions = repo.log("对齐要求.md")

        assert created == revisions[-1].at
        assert updated == revisions[0].at

    def test_a_document_that_is_not_in_history_yet_has_neither(self, repo: Repository) -> None:
        assert repo.timestamps("草稿.md") == (None, None)
