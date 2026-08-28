"""Tag normalization.

Tags are free-form: whoever writes a learning invents them. Normalizing on the way in is
what keeps the tag cloud from showing AscendC, ascend-c and ascend_c as three concepts.
"""

import re

_SEPARATORS = re.compile(r"[\s_-]+")


def normalize_tag(tag: str) -> str:
    """Lowercase, collapse whitespace and underscores to single hyphens."""
    return _SEPARATORS.sub("-", tag.strip().lstrip("#").lower()).strip("-")


def frontmatter_tags(value: object) -> list[str]:
    """Read the `tags` frontmatter field, which YAML hands back as a list or a string."""
    if isinstance(value, str):
        return [part for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize a list, dropping empties and duplicates but keeping the written order."""
    seen: dict[str, None] = {}
    for tag in tags:
        if normalized := normalize_tag(tag):
            seen[normalized] = None
    return list(seen)
