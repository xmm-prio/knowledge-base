"""Semantic Markdown: the on-disk shape of a learning.

A learning is a Markdown file that basic-memory can index down to the individual
observation. This module is the only place that knows that shape, in both directions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import frontmatter
import yaml

OBSERVATIONS_HEADING = "## Observations"
RELATIONS_HEADING = "## Relations"


@dataclass(frozen=True)
class Observation:
    """One independently searchable fact inside a document."""

    category: str
    content: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Relation:
    """A directed link from this document to another."""

    type: str
    target: str


@dataclass(frozen=True)
class Learning:
    """A reusable conclusion an agent distilled, as it is written to disk."""

    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    author: str = ""
    observations: list[Observation] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def render_learning(learning: Learning) -> str:
    """Serialize a learning to semantic Markdown."""
    parts = [_render_frontmatter(learning), f"# {learning.title}", ""]

    if learning.observations:
        parts += [OBSERVATIONS_HEADING, ""]
        parts += [_render_observation(o) for o in learning.observations]
        parts.append("")

    if learning.relations:
        parts += [RELATIONS_HEADING, ""]
        parts += [f"- {r.type} [[{r.target}]]" for r in learning.relations]
        parts.append("")

    return "\n".join(parts)


def _render_frontmatter(learning: Learning) -> str:
    metadata = {
        "title": learning.title,
        "type": "note",
        "summary": learning.summary,
        "tags": list(learning.tags),
        "author": learning.author,
    }
    # allow_unicode keeps CJK readable in the file instead of \uXXXX escapes.
    body = yaml.dump(metadata, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{body}---\n"


# Upstream reads a trailing "(...)" as the observation's context, so a line that ends in a
# call signature or an expression would lose that tail from the observation index. An empty
# context absorbs the rule and leaves the real content whole.
PAREN_GUARD = " ()"


def _render_observation(observation: Observation) -> str:
    line = f"- [{observation.category}] {observation.content}"
    for tag in observation.tags:
        line += f" #{tag}"
    if line.endswith(")"):
        line += PAREN_GUARD
    return line


# The category may not contain brackets or parens -- that is upstream's rule, not ours.
_OBSERVATION_LINE = re.compile(r"^- \[([^\[\]()]+)\]\s+(.+)$")
_RELATION_LINE = re.compile(r"^- (\S+) \[\[(.+?)\]\]\s*$")


def parse_learning(text: str) -> Learning:
    """Read a learning back from its semantic Markdown."""
    metadata, body = frontmatter.parse(text)

    observations: list[Observation] = []
    relations: list[Relation] = []
    for line in body.splitlines():
        line = line.rstrip()
        if observation := _parse_observation(line):
            observations.append(observation)
        elif relation := _RELATION_LINE.match(line):
            relations.append(Relation(type=relation.group(1), target=relation.group(2)))

    return Learning(
        title=str(metadata.get("title", "")),
        summary=str(metadata.get("summary", "")),
        tags=list(metadata.get("tags") or []),
        author=str(metadata.get("author", "")),
        observations=observations,
        relations=relations,
    )


def _parse_observation(line: str) -> Observation | None:
    match = _OBSERVATION_LINE.match(line)
    if not match:
        return None
    rest = match.group(2)
    if rest.endswith(PAREN_GUARD.strip()) and rest != PAREN_GUARD.strip():
        rest = rest[: -len(PAREN_GUARD)].rstrip()

    words = rest.split(" ")
    tags: list[str] = []
    while len(words) > 1 and words[-1].startswith("#"):
        tags.insert(0, words.pop()[1:])

    return Observation(category=match.group(1).strip(), content=" ".join(words), tags=tags)
