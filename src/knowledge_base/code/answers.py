"""Reading the upstream's answers into shapes this service is willing to stand behind.

The upstream's payloads are undocumented (ADR-0001), which has so far meant handing them to
the screen untouched and letting a generic JSON tree render whatever arrived. That is honest
about the shape and useless about the meaning: a member reading a call chain cannot tell who
calls whom, and a member reading a search result has to copy a qualified name out of a tree
by hand.

So the readers below are tolerant on the way in and strict on the way out. They look for the
handful of spellings an entry might use, and anything they cannot read is not guessed at: a
symbol without a qualified name is not a symbol, and an edge whose endpoints cannot both be
pinned to one symbol is not an edge. What could not be read is counted and reported next to
the result, because a member who is told the answer is incomplete behaves very differently
from one who is shown a confident empty list.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from knowledge_base.code.naming import readable_names, repo_key

QUALIFIED_NAME_KEYS = ("qualified_name", "qualifiedName", "qn", "symbol", "name")
"""Where an entry might keep the name that identifies it, best first."""

REPO_KEYS = ("project", "repo", "repository")

FILE_KEYS = ("file", "path", "file_path", "filePath")

LINE_KEYS = ("line", "line_number", "lineNumber", "start_line")

KIND_KEYS = ("kind", "type", "symbol_type", "node_type")

COLLECTION_KEYS = ("results", "matches", "symbols", "nodes", "items", "entries", "data")
"""What a payload might call the list inside it, when it is not simply a list."""

CALLER_KEYS = ("caller", "from", "source", "start")
CALLEE_KEYS = ("callee", "to", "target", "end")
PATH_KEYS = ("paths", "chains", "routes")
EDGE_KEYS = ("edges", "calls", "relations", "links")


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

    raw: Any = None
    """The upstream's own payload, kept whenever nothing at all could be read from it."""


@dataclass(frozen=True)
class CallNode:
    """One symbol on a call chain, and how far from the starting point it sits."""

    symbol: Symbol
    depth: int


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
    unresolved: int = 0
    """Relations the upstream reported that could not be pinned to one symbol at each end.

    Counted rather than shown: a relation that might be to any of three functions is more
    misleading than a relation that is missing, and a member who knows how many were dropped
    knows not to read an empty result as proof that nothing calls it.
    """

    raw: Any = None


def _first(entry: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if (value := entry.get(key)) not in (None, ""):
            return value
    return None


def _entries(payload: Any) -> list[Any]:
    """The list inside a payload, whatever the payload calls it."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in COLLECTION_KEYS:
            if isinstance(inside := payload.get(key), list):
                return inside
    return []


def _line(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _named(entry: Any) -> tuple[str, dict[str, Any]] | None:
    """An entry's canonical name, if it has one this service can use as an identity."""
    if isinstance(entry, str):
        return (entry, {}) if entry.strip() else None
    if not isinstance(entry, dict):
        return None
    name = _first(entry, QUALIFIED_NAME_KEYS)
    return (str(name), entry) if isinstance(name, str | int) and str(name).strip() else None


def _repo_of(entry: dict[str, Any], fallback: str | None) -> str | None:
    named = _first(entry, REPO_KEYS)
    return repo_key(str(named)) if isinstance(named, str) else fallback


def read_symbols(payload: Any, repo: str | None = None) -> SymbolMatches:
    """Read a symbol search result, dropping and counting anything without an identity."""
    found = [named for entry in _entries(payload) if (named := _named(entry)) is not None]
    unreadable = len(_entries(payload)) - len(found)
    displays = readable_names((name, _repo_of(entry, repo) or "") for name, entry in found)
    matches = [
        Symbol(
            canonical_qn=name,
            display_qn=displays[name],
            repo=_repo_of(entry, repo),
            file=str(file) if (file := _first(entry, FILE_KEYS)) is not None else None,
            line=_line(_first(entry, LINE_KEYS)),
            kind=str(kind) if (kind := _first(entry, KIND_KEYS)) is not None else None,
        )
        for name, entry in found
    ]
    return SymbolMatches(
        matches=matches,
        unreadable=unreadable,
        # Only when nothing could be read: an unrecognised payload is still evidence, and
        # throwing it away would leave a member with a blank panel and no way to say why.
        raw=payload if not matches else None,
    )


def _pairs(payload: Any) -> Iterator[tuple[Any, Any]]:
    """Every caller/callee pair the payload states, in whichever way it states them."""
    if isinstance(payload, dict):
        for key in PATH_KEYS:
            for chain in payload.get(key) or []:
                if isinstance(chain, list):
                    yield from zip(chain, chain[1:], strict=False)
        for key in EDGE_KEYS:
            for edge in payload.get(key) or []:
                if isinstance(edge, dict):
                    yield _first(edge, CALLER_KEYS), _first(edge, CALLEE_KEYS)
    for entry in _entries(payload):
        if isinstance(entry, dict) and (
            _first(entry, CALLER_KEYS) is not None or _first(entry, CALLEE_KEYS) is not None
        ):
            yield _first(entry, CALLER_KEYS), _first(entry, CALLEE_KEYS)


def read_call_chain(payload: Any, root: str, direction: str, repo: str | None = None) -> CallChain:
    """Read a traced call chain, keeping only relations with a symbol at both ends."""
    edges: list[CallEdge] = []
    unresolved = 0
    entries: dict[str, dict[str, Any]] = {}
    for caller, callee in _pairs(payload):
        ends = [_named(one) for one in (caller, callee)]
        if any(one is None for one in ends):
            unresolved += 1
            continue
        for name, entry in ends:  # type: ignore[misc]
            entries.setdefault(name, entry)
        edges.append(CallEdge(caller=ends[0][0], callee=ends[1][0]))  # type: ignore[index]

    if not edges:
        # Nothing was resolvable, so anything the upstream did say is still worth showing.
        return CallChain(root=root, direction=direction, unresolved=unresolved, raw=payload)

    displays = readable_names(
        (name, _repo_of(entry, repo) or "") for name, entry in entries.items()
    )
    depths = _depths(root, edges, direction)
    nodes = [
        CallNode(
            symbol=Symbol(
                canonical_qn=name,
                display_qn=displays[name],
                repo=_repo_of(entry, repo),
                file=str(file) if (file := _first(entry, FILE_KEYS)) is not None else None,
                line=_line(_first(entry, LINE_KEYS)),
                kind=str(kind) if (kind := _first(entry, KIND_KEYS)) is not None else None,
            ),
            depth=depths.get(name, 0),
        )
        for name, entry in entries.items()
    ]
    return CallChain(
        root=root,
        direction=direction,
        nodes=sorted(nodes, key=lambda one: (one.depth, one.symbol.display_qn)),
        edges=edges,
        unresolved=unresolved,
    )


def _depths(root: str, edges: list[CallEdge], direction: str) -> dict[str, int]:
    """How many hops each symbol sits from the one that was asked about.

    Walked in the direction the question was asked in: tracing callers, the chain grows away
    from the root along `caller`; tracing callees, along `callee`.
    """
    inbound = direction != "outbound"
    onward: dict[str, list[str]] = {}
    for edge in edges:
        here, there = (edge.callee, edge.caller) if inbound else (edge.caller, edge.callee)
        onward.setdefault(here, []).append(there)
    start = next((name for name in _reachable_names(edges) if name.endswith(root)), root)
    depths = {start: 0}
    frontier = [start]
    while frontier:
        name = frontier.pop(0)
        for adjacent in onward.get(name, []):
            if adjacent not in depths:
                depths[adjacent] = depths[name] + 1
                frontier.append(adjacent)
    return depths


def _reachable_names(edges: list[CallEdge]) -> list[str]:
    return [name for edge in edges for name in (edge.caller, edge.callee)]
