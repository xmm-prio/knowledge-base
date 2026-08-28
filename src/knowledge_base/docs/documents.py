"""What the rest of the system sees when it looks at a Markdown file.

Learnings are written in semantic Markdown and knowledge is free-form, but search, the tag
cloud and the outline all want the same handful of facts. This is that shape.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from knowledge_base.docs.notes import Observation, parse_body
from knowledge_base.docs.tags import frontmatter_tags, normalize_tags

_FIRST_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    """One Markdown file, reduced to what the gateway indexes and displays."""

    path: str
    """Relative to the knowledge base root, e.g. `learnings/ascendc/对齐要求.md`."""

    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    body: str = ""
    """Prose, without the observation and relation sections."""

    observations: list[Observation] = field(default_factory=list)


def load_document(root: Path, relative_path: str) -> Document:
    """Read one Markdown file under the knowledge base root.

    Handles both flavours: learnings carry frontmatter and observations, knowledge may be
    nothing but prose.
    """
    metadata, raw_body = frontmatter.parse((root / relative_path).read_text(encoding="utf-8"))
    body = parse_body(raw_body)

    return Document(
        path=relative_path,
        title=_title(metadata, body.prose, relative_path),
        summary=str(metadata.get("summary") or ""),
        tags=normalize_tags(frontmatter_tags(metadata.get("tags"))),
        body=body.prose,
        observations=body.observations,
    )


def _title(metadata: dict[str, object], prose: str, relative_path: str) -> str:
    """Frontmatter wins, then the first heading, then the file name."""
    if declared := str(metadata.get("title") or "").strip():
        return declared
    if heading := _FIRST_HEADING.search(prose):
        return heading.group(1).strip()
    return Path(relative_path).stem
