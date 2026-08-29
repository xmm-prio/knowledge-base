"""How the gateway names the things the upstream also names.

Two problems, one shape. The upstream spells a repository however it was handed one -- a bare
name here, an absolute path there -- and it spells a symbol as a fully qualified name whose
front half is often a flattened absolute path. Neither spelling is documented, so comparing
them and showing them have to be decisions made here rather than strings that happened to
match or happened to fit on screen.

Two rules come out of that, and both are deliberate:

- a repository is compared by its last path component, case-folded. The directory an operator
  put under `codebase/` is the identity; every path that ends in it is the same repository.
- a symbol is *shown* under its repository and its own name, and *referred to* by the
  upstream's own qualified name, unchanged. The short name is for reading. Anything that gets
  stored, linked or sent back to the upstream uses the canonical one, so shortening can never
  break a later call.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

SEPARATORS = re.compile(r"[\\/]|::")
"""How the upstream might join the parts of a name. All of them mean the same thing here."""

PATHISH = re.compile(r"^_|__|^[A-Za-z]$")
"""What a flattened filesystem path looks like once it has been made into a name segment.

A leading underscore is a rooted absolute path (`_srv_kb_codebase_mops_src`), a doubled one is
a drive or a separator run (`C__Users_...`), and a lone letter is a drive on its own.
"""

KEPT_SEGMENTS = 2
"""How much of a qualified name is worth reading: the symbol, and what encloses it."""

SHORT_ID_LENGTH = 6
"""Enough of a digest to separate two symbols on one screen, short enough to read aloud."""


def repo_key(identifier: str) -> str:
    """The comparable form of a repository identifier.

    The upstream reports a project by whatever it was given: `mops`, `/srv/kb/codebase/mops`,
    `C:\\kb\\codebase\\Mops`. All three name the directory an operator placed under
    `codebase/`, and a string comparison says only one of them does.
    """
    trimmed = SEPARATORS.sub("/", identifier).rstrip("/")
    return trimmed.rsplit("/", 1)[-1].casefold()


def display_name(canonical: str, repo: str) -> str:
    """A symbol's name as it should be read: its repository, and the tail of its own name.

    Everything in front of the last couple of segments is where the file happens to sit on
    the machine that indexed it, which is neither stable nor worth a line of screen. It is not
    lost: `canonical` travels beside this everywhere and is what any later call uses.
    """
    segments = [part for part in SEPARATORS.sub(".", canonical).split(".") if part]
    if not segments:
        return f"{repo}.{canonical}" if repo else canonical
    readable: list[str] = []
    for segment in reversed(segments):
        if PATHISH.search(segment) or len(readable) == KEPT_SEGMENTS:
            break
        readable.append(segment)
    # A name that is nothing but path still has to be called something: its own last segment.
    tail = ".".join(reversed(readable)) if readable else segments[-1]
    return f"{repo}.{tail}" if repo else tail


def short_id(canonical: str) -> str:
    """A stable few characters standing for one exact symbol."""
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:SHORT_ID_LENGTH]


def readable_names(symbols: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Display names for a set of (canonical name, repository) pairs, all distinct.

    Two symbols that read the same on screen are worse than one long name: a member clicks
    the wrong one and never finds out. So a name shared by more than one symbol earns a short
    stable identifier, and only then -- the common case stays short.
    """
    proposed = {canonical: display_name(canonical, repo) for canonical, repo in symbols}
    taken: dict[str, int] = {}
    for name in proposed.values():
        taken[name] = taken.get(name, 0) + 1
    return {
        canonical: (name if taken[name] == 1 else f"{name}#{short_id(canonical)}")
        for canonical, name in proposed.items()
    }
