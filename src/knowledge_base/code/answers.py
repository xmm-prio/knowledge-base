"""Reading the upstream's answers into shapes this service is willing to stand behind.

The upstream answers in tables (see `tables`), and what it puts in them is not always what a
question was about. Two readings here are deliberate and worth stating, because both make the
answer smaller than the raw payload:

- a symbol without a qualified name is not a symbol. It is dropped and counted, never guessed
  at, because a member who is told an answer is incomplete behaves very differently from one
  shown a confident empty list.
- a call is only claimed where the upstream says how it resolved it. Asked for evidence, it
  labels every hop `lsp`, `language_rule`, `heuristic` or `unresolved` and scores it; the
  unresolved ones are counted rather than drawn. It also reports each hop's *distance* from
  the symbol asked about and not its caller, so beyond the first hop there is no edge to
  draw at all -- knowing something is two hops away does not say through what.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from knowledge_base.code.naming import readable_names
from knowledge_base.code.tables import Row, counted, rows_of

UNRESOLVED = "unresolved"
"""How the upstream labels a hop it could not pin to one symbol."""

FIRST_HOP = 1
"""The only distance at which the upstream's answer states who is on the other end."""


@dataclass(frozen=True)
class Symbol:
    """One symbol, under two names on purpose.

    `display_qn` is for reading and `canonical_qn` is for asking. Nothing that is stored,
    linked or sent back upstream may use the first, so shortening a name can never break a
    later call.
    """

    canonical_qn: str
    display_qn: str
    repo: str | None = None
    file: str | None = None
    line: int | None = None
    kind: str | None = None


@dataclass(frozen=True)
class SymbolMatches:
    """What a symbol search found, and what of it could not be read."""

    matches: list[Symbol] = field(default_factory=list)
    unreadable: int = 0
    """Entries the upstream returned that carry no name this service could identify."""

    total: int | None = None
    """How many the upstream says exist, which is more than were returned when truncated."""

    truncated: bool = False
    """Whether a page limit stopped this short of everything that matched."""

    raw: Any = None
    """The upstream's own payload, kept whenever nothing at all could be read from it."""


@dataclass(frozen=True)
class CallNode:
    """One symbol on a call chain, how far from the starting point, and how sure we are."""

    symbol: Symbol
    depth: int
    strategy: str | None = None
    """How the upstream resolved this hop: `lsp`, `language_rule` or `heuristic`."""

    confidence: float | None = None


@dataclass(frozen=True)
class CallEdge:
    """One call this service is willing to claim, by canonical name at both ends."""

    caller: str
    callee: str


@dataclass(frozen=True)
class CallChain:
    """A call chain in the gateway's own terms, with what it could not resolve counted."""

    root: str
    direction: str
    nodes: list[CallNode] = field(default_factory=list)
    edges: list[CallEdge] = field(default_factory=list)
    """Only the first hop. The upstream reports distance from the root rather than parentage,
    so an edge between two symbols further out would be invented."""

    unresolved: int = 0
    """Hops the upstream reported without being able to pin them to one symbol.

    Counted rather than shown: a relation that might be to any of three functions is more
    misleading than a relation that is missing, and a member who knows how many were dropped
    knows not to read a short result as proof that nothing else calls it.
    """

    total: int | None = None
    truncated: bool = False
    raw: Any = None


@dataclass(frozen=True)
class SourceText:
    """One symbol's source, as the upstream cut it."""

    canonical_qn: str
    display_qn: str
    text: str
    repo: str | None = None
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    clipped_at: int | None = None
    """Where the upstream stopped, when it did. Read as the whole thing, a clipped body is
    how somebody concludes a function does not handle a case it handles on line 600."""

    raw: Any = None


def read_symbols(pages: Iterable[tuple[str | None, Any]]) -> SymbolMatches:
    """Read one search result per repository into one answer.

    Several pages rather than one because the upstream searches a single project at a time,
    and the pages have to be named together: two symbols that read alike are told apart by a
    short identifier, and deciding that per repository would let a name repeat across two of
    them without either one knowing.
    """
    read = [(repo, page, _symbol_rows(page)) for repo, page in pages]
    found = [
        (repo or "", named, row)
        for repo, _, (_, rows) in read
        for row in rows
        if (named := row.qualified_name) is not None
    ]
    displays = readable_names((named, repo) for repo, named, _ in found)
    totals = [counted(page, "total") for _, page, _ in read]
    return SymbolMatches(
        matches=[
            Symbol(
                canonical_qn=named,
                display_qn=displays[(named, repo)],
                repo=repo or None,
                file=row.where,
                line=row.line,
                kind=row.kind,
            )
            for repo, named, row in found
        ],
        unreadable=sum(len(rows) for _, _, (_, rows) in read) - len(found),
        total=_summed(total for total, _ in totals),
        truncated=any(more for _, more in totals),
        # An unrecognised payload is still evidence, and throwing it away leaves a member with
        # a blank panel and no way to say why. A payload that was recognised and holds nothing
        # is a different thing entirely -- that one is an answer, and answering "no matches"
        # by dumping the payload teaches people to distrust the empty result that is correct.
        raw=[page for _, page, _ in read] if not any(known for _, _, (known, _) in read) else None,
    )


def read_call_chain(payload: Any, root: str, direction: str, repo: str | None = None) -> CallChain:
    """Read a traced call chain, keeping only the hops the upstream stands behind."""
    sections = _call_sections(payload)
    hops = [
        (way, named, row)
        for way, section in sections
        for row in rows_of(section)
        if (named := row.qualified_name) is not None and row.text("strategy") != UNRESOLVED
    ]
    unresolved = sum(1 for _, section in sections for _ in rows_of(section)) - len(hops)
    total, truncated = _call_totals(payload)

    if not hops:
        # Nothing was resolvable, so anything the upstream did say is still worth showing.
        return CallChain(
            root=root,
            direction=direction,
            unresolved=unresolved,
            total=total,
            truncated=truncated,
            raw=payload,
        )

    displays = readable_names((named, repo or "") for _, named, _ in hops)
    nodes = [
        CallNode(
            symbol=Symbol(
                canonical_qn=named,
                display_qn=displays[(named, repo or "")],
                repo=repo,
                file=row.where,
                line=row.line,
                kind=row.kind,
            ),
            depth=row.number("hop") or FIRST_HOP,
            strategy=row.text("strategy"),
            confidence=row.decimal("confidence"),
        )
        for _, named, row in hops
    ]
    return CallChain(
        root=root,
        direction=direction,
        nodes=sorted(nodes, key=lambda one: (one.depth, one.symbol.display_qn)),
        edges=[
            CallEdge(caller=named, callee=root) if way == "callers" else CallEdge(root, named)
            for (way, named, row), node in zip(hops, nodes, strict=True)
            if node.depth == FIRST_HOP
        ],
        unresolved=unresolved,
        total=total,
        truncated=truncated,
    )


def read_source(payload: Any, qualified_name: str, repo: str | None = None) -> SourceText | None:
    """Read one symbol's source, or None if the payload is not one."""
    if not isinstance(payload, dict) or not isinstance(source := payload.get("source"), str):
        return None
    named = payload.get("qualified_name")
    canonical = named if isinstance(named, str) and named.strip() else qualified_name
    displays = readable_names([(canonical, repo or "")])
    return SourceText(
        canonical_qn=canonical,
        display_qn=displays[(canonical, repo or "")],
        text=source,
        repo=repo,
        file=_relative(payload.get("file_path"), payload.get("name")),
        start_line=_whole(payload.get("start_line")),
        end_line=_whole(payload.get("end_line")),
        clipped_at=_whole(payload.get("clipped_at_lines"))
        if payload.get("source_clipped")
        else None,
    )


def _symbol_rows(payload: Any) -> tuple[bool, list[Row]]:
    """The rows of a search answer, and whether the answer was one this service understood.

    Understanding it matters separately from finding anything in it: a search that legitimately
    matched nothing and a payload in a shape nobody here recognises both yield no rows, and
    only one of them should be shown to a member as a payload dump.

    The upstream answers in tables. The tolerant branch stays because the shape is not part of
    any contract we were given: a version that answers in plain objects should degrade to a
    readable list rather than to an empty one.
    """
    if isinstance(payload, dict) and "cols" in payload:
        return True, list(rows_of(payload))
    loose = _loose_entries(payload)
    rows = [
        Row(entry) if isinstance(entry, dict) else Row({"qn": entry})
        for entry in loose
        if isinstance(entry, dict) or (isinstance(entry, str) and entry.strip())
    ]
    return bool(loose), rows


def _loose_entries(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "matches", "symbols", "nodes", "items", "entries", "data"):
            if isinstance(inside := payload.get(key), list):
                return inside
    return []


def _call_sections(payload: Any) -> list[tuple[str, Any]]:
    """The traced hops, under the heading that says which way they run."""
    if not isinstance(payload, dict):
        return []
    return [
        (way, payload[way]) for way in ("callers", "callees") if isinstance(payload.get(way), dict)
    ]


def _call_totals(payload: Any) -> tuple[int | None, bool]:
    if not isinstance(payload, dict):
        return None, False
    totals = [
        found
        for way in ("callers_total", "callees_total")
        if (found := _whole(payload.get(way))) is not None
    ]
    truncated = any(counted(payload.get(way), "total")[1] for way in ("callers", "callees"))
    return (sum(totals) if totals else None), truncated or bool(payload.get("next"))


def _summed(totals: Iterable[int | None]) -> int | None:
    """How many matched in total, when every page said. One page that did not makes the sum
    a smaller number presented as a complete one, which is worse than saying nothing."""
    counts = list(totals)
    return sum(one for one in counts if one is not None) if counts and None not in counts else None


def _whole(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _relative(absolute: Any, fallback: Any) -> str | None:
    """The path to show. The upstream gives an absolute one and, beside it, the repository
    relative one it calls the node's name."""
    if isinstance(fallback, str) and "/" in fallback:
        return fallback
    return absolute.strip() or None if isinstance(absolute, str) else None
