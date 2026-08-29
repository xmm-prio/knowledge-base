"""Which directory on disk is which project upstream.

The upstream names a project by flattening the path it was handed at index time:
`/home/mdc/mops-knowledge-base/codebase/ops-nn` becomes
`home-mdc-mops-knowledge-base-codebase-ops-nn`. That spelling is derived, undocumented and
not something either side should reconstruct by hand -- and every read tool the upstream
offers takes it as a required `project` argument, so getting it wrong is not a degraded
answer but no answer at all.

`list_projects` carries `root_path` beside each name. A directory is a directory: that is the
join, and it holds for projects indexed before this module existed as well as after.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

from knowledge_base.code.upstream import UpstreamUnavailable

logger = logging.getLogger(__name__)

PAGE = 100
"""How many projects to ask for at once. The upstream caps `limit` here and pages the rest."""

MAX_PAGES = 50
"""A stop, so a upstream that always reports `has_more` cannot spin this forever."""


class NotIndexed(ValueError):
    """The upstream has no project for this repository, so there is nothing to ask it about.

    Raised instead of sending the question: every read tool requires a `project`, so a
    repository the upstream has never indexed produces a refusal whose wording is about a
    missing argument. What happened is worth saying plainly, and it is fixable by whoever
    is reading it.
    """


class Upstream(Protocol):
    """Whatever can answer an upstream tool call."""

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class Project:
    """One repository as the upstream knows it."""

    name: str
    """The identifier every upstream read tool requires. Never shown to a member."""

    root: Path
    """Where the upstream found it. The only thing about a project we can match on."""


class Catalog:
    """The upstream's projects, addressable by the directory they were indexed from.

    Built from one listing, then read many times: resolving a repository must not cost an
    upstream call per question. It is a snapshot by construction -- a repository indexed after
    it was built is absent until the next one -- which is what callers want, since a listing
    and the answers derived from it should agree with each other.
    """

    def __init__(self, projects: Iterator[Project] | list[Project]) -> None:
        self._by_root = {_comparable(project.root): project for project in projects}

    @classmethod
    def read_from(cls, upstream: Upstream) -> Catalog:
        """Ask the upstream what it has indexed, and fail if it cannot say.

        Used before asking a question, where an empty catalog and an absent binary must not
        arrive at the same answer: "this repository is not indexed" sends a member to index
        it, and no amount of indexing helps when the binary is not running.
        """
        return cls(_all_projects(upstream))

    @classmethod
    def best_effort(cls, upstream: Upstream) -> Catalog:
        """The same, for listing what is on disk beside what the upstream knows.

        A silent binary must not make a knowledge base look empty of sources, so a failure
        here is an empty catalog: every repository is shown, none of them as indexed.
        """
        try:
            return cls.read_from(upstream)
        except UpstreamUnavailable:
            # Whoever failed to start the upstream has already said so, once. Repeating it
            # here on every listing buries the reasons worth reading.
            logger.debug("no upstream to list indexed projects")
        except Exception:
            logger.warning("upstream could not list indexed projects", exc_info=True)
        return cls([])

    def of(self, location: Path) -> Project | None:
        """The project indexed from this directory, if the upstream has one."""
        return self._by_root.get(_comparable(location))

    def __len__(self) -> int:
        return len(self._by_root)


def _all_projects(upstream: Upstream) -> Iterator[Project]:
    """Every page of the listing, as projects we can match against a directory."""
    offset = 0
    for _ in range(MAX_PAGES):
        payload = upstream.call_tool("list_projects", {"offset": offset, "limit": PAGE})
        entries = _entries(payload)
        yield from _read(entries)
        offset += len(entries)
        if not (isinstance(payload, dict) and payload.get("has_more")) or not entries:
            return
    logger.warning("stopped reading the project listing after %d pages", MAX_PAGES)


def _entries(payload: object) -> list[object]:
    if isinstance(payload, dict):
        listed = payload.get("projects")
        return listed if isinstance(listed, list) else []
    return payload if isinstance(payload, list) else []


def _read(entries: list[object]) -> Iterator[Project]:
    """Projects we can place on disk. One the upstream reports without a root is not one of
    ours to match: we would be back to guessing at its name."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, root = entry.get("name"), entry.get("root_path")
        if isinstance(name, str) and isinstance(root, str) and name and root:
            yield Project(name=name, root=Path(root))
        else:
            logger.info("upstream listed a project without a usable root: %r", entry)


def _comparable(location: Path | str) -> str:
    """One spelling of a directory, so two spellings of the same one compare equal.

    The upstream reports the path in its own operating system's terms and may or may not
    leave a trailing separator on it; the case-fold matters on Windows and costs nothing
    where it does not. Symlinks are deliberately not resolved: the upstream indexed the path
    it was given, and that is the path it answers to.
    """
    text = str(location).strip()
    separated = PureWindowsPath(text) if "\\" in text else PurePosixPath(text)
    return str(separated).rstrip("/\\").casefold()
