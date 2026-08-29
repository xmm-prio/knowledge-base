"""The column-oriented shape the upstream answers in, read once for everybody.

Asked for JSON, `search_graph` and `trace_path` answer with a table rather than a list of
objects: `cols` names the columns, and the payload carries either flat `rows` or `groups`,
each group holding the part of the qualified name its rows share.

    {"cols": ["name", "label", "lines", "in", "out"],
     "groups": [{"qn_prefix": "...op_kernel.mat_mul", "file": "matmul/...h",
                 "rows": [["AMatMulB", "Function", "725-788", 1, 1]]}]}

A row is therefore only meaningful beside the columns and the group it came from -- the
qualified name to ask the upstream with next is the prefix and the name joined -- so nothing
downstream should ever see a bare row. This module hands out rows already put back together.

The same tool answers in the other shape when it is asked a ranked question instead of a
pattern: flat `rows`, and the whole qualified name in a `qn` column. Both arrive here as the
same thing, because to a caller they are the same answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

NAME_COLUMNS = ("qn", "qualified_name")
"""Columns that carry a whole qualified name. A `name` column carries only its last part."""

FILE_COLUMNS = ("file", "file_path", "path")

KIND_COLUMNS = ("label", "kind")

LINE_COLUMNS = ("lines", "line", "start_line")


@dataclass(frozen=True)
class Row:
    """One row, with the columns named and the group's context folded in."""

    values: dict[str, Any]
    prefix: str | None = None
    """The qualified name every row in this group shares, when it came from one."""

    file: str | None = None

    @property
    def qualified_name(self) -> str | None:
        """The name to ask the upstream with, or None if this row does not identify one."""
        for column in NAME_COLUMNS:
            if isinstance(whole := self.values.get(column), str) and whole.strip():
                return whole.strip()
        last = self.values.get("name")
        if not isinstance(last, str) or not last.strip():
            return None
        return f"{self.prefix}.{last.strip()}" if self.prefix else last.strip()

    @property
    def where(self) -> str | None:
        for column in FILE_COLUMNS:
            if isinstance(named := self.values.get(column), str) and named.strip():
                return named.strip()
        return self.file

    @property
    def kind(self) -> str | None:
        for column in KIND_COLUMNS:
            if isinstance(named := self.values.get(column), str) and named.strip():
                return named.strip()
        return None

    @property
    def line(self) -> int | None:
        """Where it starts. The upstream states a span, `725-788`, and the start is the part
        anybody navigates by."""
        for column in LINE_COLUMNS:
            if (found := _starting(self.values.get(column))) is not None:
                return found
        return None

    def number(self, column: str) -> int | None:
        return _whole(self.values.get(column))

    def decimal(self, column: str) -> float | None:
        try:
            return float(self.values[column])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return None

    def text(self, column: str) -> str | None:
        found = self.values.get(column)
        return str(found).strip() or None if found is not None else None


def rows_of(section: Any) -> Iterator[Row]:
    """Every row of one table, whichever of the two shapes it arrived in."""
    if not isinstance(section, dict) or not isinstance(columns := section.get("cols"), list):
        return
    named = [str(one) for one in columns]
    for group in section.get("groups") or []:
        if not isinstance(group, dict):
            continue
        prefix, file = _string(group.get("qn_prefix")), _string(group.get("file"))
        for row in group.get("rows") or []:
            yield Row(_named(named, row), prefix, file)
    for row in section.get("rows") or []:
        yield Row(_named(named, row))


def counted(section: Any, *columns: str) -> tuple[int | None, bool]:
    """How many the upstream says there are, and whether this page is short of them."""
    if not isinstance(section, dict):
        return None, False
    total = next(
        (found for one in columns if (found := _whole(section.get(one))) is not None), None
    )
    return total, bool(section.get("has_more"))


def _named(columns: list[str], row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return dict(zip(columns, row, strict=False)) if isinstance(row, list) else {}


def _string(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _whole(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _starting(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (head := value.split("-", 1)[0].strip()).isdigit():
        return int(head)
    return None
