"""Reading what `search_code` says, which is text and only text.

Every other read tool takes `format: "json"`. This one has no such argument, so a full-text
search comes back as the upstream's own report:

    results: 2  (cols: qn label file lines matches in out)
      <qualified name> Function conv/.../aclnn_convolution.cpp 5384-5464 5411;5415 9 9
    raw: 12  (cols: file line content)
      conv/deformable_conv2d/op_kernel/base.h 24 "constexpr MatmulConfig MDL_CFG = ..."
    total_grep_matches: 500
    total_results: 217

Two sections matter and they answer different questions. `results` is the declarations the
matches fall inside, which is what makes a hit clickable -- the same symbols the other search
modes return, so a member can read the source or trace the calls from here too. `raw` is the
matching lines themselves, which is the only thing that finds a comment or a language the
upstream never parsed.

Columns are separated by spaces and a path could contain one, so rows are read from both ends
inward: the trailing columns are counts of known arity and everything left over in the middle
is the path. A row that does not fit is dropped and counted rather than bent to fit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from knowledge_base.code.answers import Symbol
from knowledge_base.code.naming import readable_names

HEADING = re.compile(r"^(?P<section>results|raw|dirs):\s*(?P<count>\d+)")
"""How each section announces itself and how many rows it holds."""

TALLY = re.compile(r"^(?P<name>total_grep_matches|total_results|raw_match_count):\s*(?P<count>\d+)")

RESULT_COLUMNS = 7
"""qn, label, file, lines, matches, in, out -- the last four counted from the right."""

RAW_COLUMNS = 3
"""file, line, content -- the content is everything after the line number."""


@dataclass(frozen=True)
class GrepLine:
    """One matching line of source, as it reads in the file."""

    file: str
    line: int | None
    text: str


@dataclass(frozen=True)
class TextMatches:
    """What a full-text search found: the declarations around it, and the lines themselves."""

    symbols: list[Symbol] = field(default_factory=list)
    lines: list[GrepLine] = field(default_factory=list)
    total: int | None = None
    """Matching lines the upstream counted, which is more than it returned when truncated."""

    truncated: bool = False
    unreadable: int = 0
    raw: Any = None
    """The upstream's own report, kept whenever nothing at all could be read from it."""


@dataclass(frozen=True)
class Report:
    """One repository's grep report, split up but not yet interpreted."""

    sections: dict[str, list[list[str]]] = field(default_factory=dict)
    tallies: dict[str, int] = field(default_factory=dict)

    def rows(self, section: str) -> list[list[str]]:
        return self.sections.get(section, [])

    @property
    def truncated(self) -> bool:
        """Whether grep found more than the upstream chose to hand back."""
        found = self.tallies.get("total_grep_matches")
        return found is not None and found > len(self.rows("raw"))


def read_text_matches(pages: Iterable[tuple[str | None, Any]]) -> TextMatches:
    """Read one grep report per repository into one answer."""
    read = [(repo or "", _report(page), page) for repo, page in pages]
    found = [
        (repo, named, row)
        for repo, report, _ in read
        for row in report.rows("results")
        if (named := _declaration(row)) is not None
    ]
    lines = [
        line
        for _, report, _ in read
        for row in report.rows("raw")
        if (line := _matching_line(row)) is not None
    ]
    displays = readable_names((named, repo) for repo, named, _ in found)
    counted = [report.tallies.get("total_grep_matches") for _, report, _ in read]
    offered = sum(len(report.rows("results")) + len(report.rows("raw")) for _, report, _ in read)
    return TextMatches(
        symbols=[
            Symbol(
                canonical_qn=named,
                display_qn=displays[(named, repo)],
                repo=repo or None,
                file=_span(row, 2, -4),
                line=_starting(_word(row, -4)),
                kind=_word(row, 1),
            )
            for repo, named, row in found
        ],
        lines=lines,
        total=sum(one for one in counted if one is not None) if counted else None,
        truncated=any(report.truncated for _, report, _ in read),
        unreadable=offered - len(found) - len(lines),
        raw=[page for _, _, page in read] if not found and not lines else None,
    )


def _report(payload: Any) -> Report:
    """Split one report into its sections, each row already split into words."""
    if not isinstance(payload, str):
        return Report()
    sections: dict[str, list[list[str]]] = {}
    tallies: dict[str, int] = {}
    inside: str | None = None
    for line in payload.splitlines():
        if (heading := HEADING.match(line)) is not None:
            inside = str(heading.group("section"))
            sections.setdefault(inside, [])
        elif (tally := TALLY.match(line)) is not None:
            inside = None
            tallies[tally.group("name")] = int(tally.group("count"))
        elif inside is not None and line.startswith(" ") and line.strip():
            sections[inside].append(line.split())
    return Report(sections=sections, tallies=tallies)


def _declaration(row: list[str]) -> str | None:
    """The qualified name a match falls inside, if the row is one this service can read."""
    return row[0] if len(row) >= RESULT_COLUMNS and row[0] else None


def _matching_line(row: list[str]) -> GrepLine | None:
    if len(row) < RAW_COLUMNS or not row[1].isdigit():
        return None
    return GrepLine(file=row[0], line=int(row[1]), text=_unquoted(" ".join(row[2:])))


def _span(row: list[str], start: int, stop: int) -> str | None:
    return " ".join(row[start:stop]).strip() or None


def _word(row: list[str], index: int) -> str | None:
    try:
        return row[index] or None
    except IndexError:
        return None


def _unquoted(text: str) -> str:
    stripped = text.strip()
    quoted = len(stripped) >= 2 and stripped[0] == stripped[-1] == '"'
    return stripped[1:-1] if quoted else stripped


def _starting(span: str | None) -> int | None:
    if span is None:
        return None
    head = span.split("-", 1)[0].strip()
    return int(head) if head.isdigit() else None
