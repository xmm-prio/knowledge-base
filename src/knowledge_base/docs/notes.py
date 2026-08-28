"""Semantic Markdown: the on-disk shape of a learning.

A learning is a Markdown file that basic-memory can index down to the individual
observation. This module is the only place that knows that shape, in both directions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
