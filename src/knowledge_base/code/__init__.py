"""The code domain: indexed source repositories, questioned through one facade.

Wiring it up is three lines, and they are the only place the pieces meet:

    supervisor = Supervisor(CbmBinary(root))
    supervisor.start()
    engine = CodeEngine(root, supervisor)
"""

from knowledge_base.code.engine import (
    CodeAnswer,
    CodeEngine,
    Direction,
    IndexOutcome,
    Repo,
    SearchMode,
    UnknownRepo,
)
from knowledge_base.code.process import CbmBinary
from knowledge_base.code.supervisor import Supervisor
from knowledge_base.code.upstream import (
    UpstreamError,
    UpstreamFailed,
    UpstreamRefused,
    UpstreamUnavailable,
)

__all__ = [
    "CbmBinary",
    "CodeAnswer",
    "CodeEngine",
    "Direction",
    "IndexOutcome",
    "Repo",
    "SearchMode",
    "Supervisor",
    "UnknownRepo",
    "UpstreamError",
    "UpstreamFailed",
    "UpstreamRefused",
    "UpstreamUnavailable",
]
