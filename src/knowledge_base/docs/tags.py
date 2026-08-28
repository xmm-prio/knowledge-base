"""Tag normalization.

Tags are free-form: whoever writes a learning invents them. Normalizing on the way in is
what keeps the tag cloud from showing AscendC, ascend-c and ascend_c as three concepts.
"""

import re

_SEPARATORS = re.compile(r"[\s_-]+")


def normalize_tag(tag: str) -> str:
    """Lowercase, collapse whitespace and underscores to single hyphens."""
    return _SEPARATORS.sub("-", tag.strip().lstrip("#").lower()).strip("-")


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize a list, dropping empties and duplicates but keeping the written order."""
    seen: dict[str, None] = {}
    for tag in tags:
        if normalized := normalize_tag(tag):
            seen[normalized] = None
    return list(seen)
