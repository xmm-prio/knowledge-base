"""Tests for debounced auto-commit.

Committing on every write would bury the history in noise -- one commit per observation an
agent distills. Debouncing is what makes git usable as the version mechanism.
"""

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from knowledge_base.vcs import AutoCommitter, Repository

QUIET = timedelta(seconds=30)


class FakeClock:
    """Time under test control, so the quiet period costs nothing to cross."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path)
    repository.ensure()
    return repository


def commits(path: Path) -> list[str]:
    log = subprocess.run(
        ["git", "log", "--pretty=%an|%s"],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in log.stdout.splitlines() if line]


def write(repo: Repository, committer: AutoCommitter, author: str, name: str) -> None:
    path = repo.path / name
    path.write_text("经验", encoding="utf-8")
    committer.record(author, path)


def files_in(path: Path, revision: str) -> list[str]:
    listing = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", revision],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return sorted(line for line in listing.stdout.splitlines() if line)


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
