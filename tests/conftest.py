"""Shared test helpers."""

import asyncio
import subprocess
from pathlib import Path


class ManualSleep:
    """A background loop's waiting, under test control.

    Stands in for `asyncio.sleep`, so a loop that runs every thirty seconds can be driven
    beat by beat without a test ever waiting for real time to pass.
    """

    def __init__(self) -> None:
        self.intervals: list[float] = []
        self._waiting = asyncio.Event()
        self._resume = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.intervals.append(seconds)
        self._waiting.set()
        await self._resume.wait()
        self._resume.clear()

    async def tick(self) -> None:
        """Let the loop round exactly once, and return only when it has."""
        await self._waiting.wait()
        self._waiting.clear()
        self._resume.set()
        await self._waiting.wait()


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
