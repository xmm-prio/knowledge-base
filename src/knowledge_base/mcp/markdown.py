"""Reading a Markdown body the way a table of contents does."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Heading:
    at: int
    level: int
    name: str


def headings(body: str) -> list[str]:
    """Every heading in the body, top to bottom, without its hashes."""
    return [heading.name for heading in _headings(body.splitlines())]


def section(body: str, name: str) -> str | None:
    """The lines under one heading, down to the next heading of the same or higher level.

    None when the body has no such heading.
    """
    lines = body.splitlines()
    found = _headings(lines)
    start = next((heading for heading in found if heading.name == name), None)
    if start is None:
        return None
    end = next(
        (h.at for h in found if h.at > start.at and h.level <= start.level),
        len(lines),
    )
    return "\n".join(lines[start.at : end]).strip()


def _headings(lines: list[str]) -> list[Heading]:
    return [
        Heading(at=at, level=len(match.group(1)), name=match.group(2))
        for at, line in enumerate(lines)
        if (match := _HEADING.match(line))
    ]
