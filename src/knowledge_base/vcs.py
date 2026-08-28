"""Git is the version history of the knowledge base. This module owns every git invocation."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
