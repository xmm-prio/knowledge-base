"""The on-disk layout of a knowledge base root."""

import re
from pathlib import Path

from knowledge_base.vcs import Repository


class OutsideLearnings(ValueError):
    """A caller asked to write somewhere agents are not allowed to write."""


# A leading separator or a drive letter means the caller handed us an absolute location.
# Rejecting it here rather than letting pathlib decide keeps the boundary identical on
# every platform: "C:/Windows" must not become a directory named "C:" on Linux.
_ANCHORED = re.compile(r"^(?:[/\\]|[A-Za-z]:)")
_SEPARATOR = re.compile(r"[/\\]")

CONTENT_DIRECTORIES = ("knowledge", "learnings", "codebase")

RUNTIME_DIRECTORY = ".knowledge-base"

# basic-memory only reads the root .gitignore, and understands nothing beyond plain
# directory-name patterns -- no negation, no ** semantics. Keep these patterns naive.
IGNORED_PATTERNS = ("codebase/", f"{RUNTIME_DIRECTORY}/")


def _contained_parts(text: str) -> list[str]:
    """Split a caller-supplied fragment into path parts, refusing anything that climbs."""
    if _ANCHORED.match(text):
        raise OutsideLearnings(f"{text!r} is an absolute location")
    parts = [part for part in _SEPARATOR.split(text.strip()) if part not in ("", ".")]
    if ".." in parts:
        raise OutsideLearnings(f"{text!r} climbs out of learnings/")
    return parts


class KnowledgeBaseRoot:
    """A directory that holds one knowledge base."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def knowledge_dir(self) -> Path:
        return self.path / "knowledge"

    @property
    def learnings_dir(self) -> Path:
        return self.path / "learnings"

    @property
    def codebase_dir(self) -> Path:
        return self.path / "codebase"

    @property
    def runtime_dir(self) -> Path:
        """Upstream indexes live here; deleting it costs nothing but a reindex."""
        return self.path / RUNTIME_DIRECTORY

    def resolve_learning_path(self, folder: str, title: str) -> Path:
        """Where a learning with this folder and title belongs.

        Raises OutsideLearnings if the result would land anywhere else. Nothing else
        enforces the agent write boundary, so this refuses rather than sanitizes.
        """
        parts = _contained_parts(folder) + _contained_parts(title)
        if not parts:
            raise OutsideLearnings("a learning needs a title")

        learnings = self.learnings_dir.resolve()
        candidate = learnings.joinpath(*parts[:-1], f"{parts[-1]}.md")

        # resolve() also walks symlinks, so a link planted inside learnings cannot be
        # used as a door out of it.
        resolved = candidate.resolve()
        if not resolved.is_relative_to(learnings):
            raise OutsideLearnings(f"{folder}/{title} resolves outside learnings/")
        return resolved

    def initialize(self) -> None:
        """Create the layout. Safe to run against an already-initialized root."""
        for name in CONTENT_DIRECTORIES:
            (self.path / name).mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_ignored()
        Repository(self.path).ensure()

    def _ensure_ignored(self) -> None:
        gitignore = self.path / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
        missing = [p for p in IGNORED_PATTERNS if p not in existing]
        if not missing:
            return
        gitignore.write_text("\n".join(existing + missing) + "\n", encoding="utf-8")
