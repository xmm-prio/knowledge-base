"""Shared test helpers."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from knowledge_base.code.process import EXECUTABLE, CbmBinary, upstream_environment
from knowledge_base.layout import KnowledgeBaseRoot

if TYPE_CHECKING:
    from api_harness import ApiHarness

CACHE_CONFLICT = "different cache directory"
"""How the upstream refuses when another daemon already holds this account's cache."""


def set_auto_watch(root: KnowledgeBaseRoot) -> subprocess.CompletedProcess[str]:
    """Ask the real binary to turn its watcher off, and hand back how that went."""
    (root.runtime_dir / "cbm").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [EXECUTABLE, "config", "set", "auto_watch", "false"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=upstream_environment(root),
        cwd=root.path,
    )


def require_upstream(root: KnowledgeBaseRoot) -> CbmBinary:
    """The real binary, driven against this root -- or a skip saying why it cannot be.

    Its coordinating daemon is per account and holds exactly one cache directory, while each
    test builds its own root and therefore its own cache. So a knowledge-base service running
    as the same user makes every one of these tests impossible, and that is worth saying out
    loud rather than failing as if the code were broken.
    """
    binary = CbmBinary(root)
    if not binary.installed:
        pytest.skip("codebase-memory-mcp is not installed")
    if CACHE_CONFLICT in set_auto_watch(root).stderr:
        pytest.skip(
            "another CBM daemon holds this account's cache: stop the knowledge-base service "
            "(or run `codebase-memory-mcp daemon stop`) before driving the real binary"
        )
    return binary


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


@pytest.fixture(autouse=True)
def upstream_contract_is_kept() -> Iterator[None]:
    """Fail any test that sends the upstream an argument it does not have.

    The real binary ignores an argument it does not recognise, so a misspelled one is
    invisible until someone reads a log and wonders why a filter never applied. Here it is
    the test's problem, at the moment it happens.
    """
    from upstream_doubles import VIOLATIONS

    VIOLATIONS.clear()
    yield
    broken, _ = list(VIOLATIONS), VIOLATIONS.clear()
    assert not broken, "the upstream would not understand these: " + "; ".join(sorted(set(broken)))


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    """A running REST API over a real document domain. Built in `api_harness`."""
    from api_harness import running_api

    async with running_api(tmp_path) as harness:
        yield harness
