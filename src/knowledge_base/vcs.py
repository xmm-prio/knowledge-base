"""Git is the version history of the knowledge base. This module owns every git invocation."""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

AUTHOR_EMAIL_DOMAIN = "knowledge-base.local"

DEFAULT_LOG_LENGTH = 50

# Only an object name may be handed to git as a revision. A caller-supplied string that
# begins with a dash would otherwise be read as an option by the process below us.
_OBJECT_NAME = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)

_FIELD = "\x1f"
"""Separates log fields. Commit subjects may contain anything printable, so the separator
has to be something a person cannot type."""


class GitError(RuntimeError):
    """A git invocation failed."""


class NoSuchRevision(ValueError):
    """No such commit, or that document is not in it."""


@dataclass(frozen=True)
class Revision:
    """One commit, as the history page shows it."""

    revision: str
    """The full object name. Short names are ambiguous once a history grows."""

    author: str
    message: str
    at: str
    """The author date, ISO-8601 with an offset. Documents carry no timestamp of their own
    (ADR-0003), so this is the only answer to when something changed."""


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
        # A path that is gone and was never tracked is not a change git can be told about:
        # `add` fails on a pathspec matching nothing, which would take the whole commit down.
        pathspecs = [str(p) for p in paths if p.exists() or self._tracked(p)]
        if not pathspecs:
            return False
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

    def log(
        self, relative_path: str | None = None, limit: int = DEFAULT_LOG_LENGTH
    ) -> list[Revision]:
        """The commits touching one document, or the whole knowledge base, newest first."""
        if not self._has_history:
            return []
        arguments = ["log", f"--max-count={limit}", f"--pretty=%H{_FIELD}%an{_FIELD}%aI{_FIELD}%s"]
        if relative_path is not None:
            arguments += ["--", relative_path]
        return [_revision(line) for line in self._git(*arguments).splitlines() if line]

    def paths_in(self, revision: str) -> list[str]:
        """The documents one commit touched."""
        listing = self._git("show", "--name-only", "--pretty=", _verified(revision))
        return sorted(line for line in listing.splitlines() if line)

    def file_at(self, revision: str, relative_path: str) -> str:
        """One document's text as it stood at a revision.

        Raises NoSuchRevision when the commit is unknown or held no such document, which is
        what stops a rollback from turning into a deletion nobody asked for.
        """
        try:
            return self._git("show", f"{_verified(revision)}:{relative_path}")
        except GitError as missing:
            raise NoSuchRevision(f"{relative_path} is not in {revision}") from missing

    def timestamps(self, relative_path: str) -> tuple[str | None, str | None]:
        """When a document first entered history and when it last changed.

        Both are None while it has never been committed -- a document written seconds ago is
        waiting out its quiet period, not missing.
        """
        if not self._has_history:
            return None, None
        listing = self._git("log", "--pretty=%aI", "--", relative_path)
        dates = [line for line in listing.splitlines() if line]
        if not dates:
            return None, None
        return dates[-1], dates[0]

    def _tracked(self, path: Path) -> bool:
        return bool(self._git("ls-files", "--", str(path)).strip())

    @property
    def _has_history(self) -> bool:
        """A repository with no commit yet answers every log with an error, not an empty list."""
        try:
            self._git("rev-parse", "--verify", "--quiet", "HEAD")
        except GitError:
            return False
        return True

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            # Document titles are Chinese, and git octal-escapes non-ASCII paths by default,
            # which would turn every filename we read back into mojibake.
            ["git", "-c", "core.quotepath=false", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout


def _verified(revision: str) -> str:
    if not _OBJECT_NAME.match(revision):
        raise NoSuchRevision(f"{revision!r} is not a commit id")
    return revision


def _revision(line: str) -> Revision:
    name, author, at, message = line.split(_FIELD, 3)
    return Revision(revision=name, author=author, message=message, at=at)


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

    def commit_alone(self, author: str, path: Path, message: str) -> bool:
        """Commit one change immediately, under its own message.

        For the changes a person makes on purpose -- a rollback -- and expects to see in
        history at once. Whatever was pending is committed first, so a deliberate act never
        drags somebody else's unrelated writes under its message.
        """
        self._commit()
        return self._repository.commit(message, author, [path])

    def _commit(self) -> bool:
        if self._author is None:
            return False
        author, paths = self._author, list(self._pending)
        self._author, self._pending = None, {}
        return self._repository.commit(f"{author} 沉淀了 {len(paths)} 处改动", author, paths)
