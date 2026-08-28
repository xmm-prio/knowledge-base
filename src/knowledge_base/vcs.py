"""Git is the version history of the knowledge base. This module owns every git invocation."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

AUTHOR_EMAIL_DOMAIN = "knowledge-base.local"


class GitError(RuntimeError):
    """A git invocation failed."""


class Repository:
    """The git repository at a knowledge base root."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return (self.path / ".git").is_dir()

    def ensure(self) -> None:
        """Create the repository unless the operator already made one."""
        if self.exists:
            return
        self._git("init", "-q")
        self._git("symbolic-ref", "HEAD", "refs/heads/main")

    def commit(self, message: str, author: str, paths: list[Path]) -> bool:
        """Commit exactly these paths as `author`. False when there was nothing to commit."""
        pathspecs = [str(p) for p in paths]
        self._git("add", "-A", "--", *pathspecs)
        if not self._git("diff", "--cached", "--name-only", "--", *pathspecs).strip():
            return False
        self._git(
            "-c",
            f"user.name={author}",
            "-c",
            f"user.email={author}@{AUTHOR_EMAIL_DOMAIN}",
            "commit",
            "-q",
            "-m",
            message,
            "--",
            *pathspecs,
        )
        return True

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout


class AutoCommitter:
    """Turns a stream of writes into a readable history.

    Writes are held back until the author goes quiet, so a burst of distillation becomes one
    commit instead of one per observation. A different author always starts a new commit --
    history is only useful if it says who concluded what.
    """

    def __init__(
        self,
        repository: Repository,
        quiet_period: timedelta,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._quiet_period = quiet_period.total_seconds()
        self._clock = clock
        self._author: str | None = None
        # An ordered set: rewriting one file during a burst is still one change.
        self._pending: dict[Path, None] = {}
        self._last_write = 0.0

    def record(self, author: str, path: Path) -> None:
        """Note that `author` just wrote `path`."""
        if self._author is not None and author != self._author:
            self._commit()
        self._author = author
        self._pending[path] = None
        self._last_write = self._clock()

    def flush_due(self) -> bool:
        """Commit if the current author has been quiet long enough. Safe to call on a timer."""
        if self._author is None:
            return False
        if self._clock() - self._last_write < self._quiet_period:
            return False
        return self._commit()

    def flush_now(self) -> bool:
        """Commit whatever is pending, without waiting. For shutdown."""
        return self._commit()

    def _commit(self) -> bool:
        if self._author is None:
            return False
        author, paths = self._author, list(self._pending)
        self._author, self._pending = None, {}
        return self._repository.commit(f"{author} 沉淀了 {len(paths)} 处改动", author, paths)
