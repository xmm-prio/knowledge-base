"""Shared test helpers."""

import subprocess
from pathlib import Path


class FakeClock:
    """Time under test control, so a quiet period costs nothing to cross."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def commits(path: Path) -> list[str]:
    """Every commit as `author|subject`, newest first."""
    return [line for line in _git(path, "log", "--pretty=%an|%s").splitlines() if line]


def files_in(path: Path, revision: str) -> list[str]:
    """The files one commit touched."""
    listing = _git(path, "show", "--name-only", "--pretty=", revision)
    return sorted(line for line in listing.splitlines() if line)
