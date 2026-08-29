"""What went wrong with a code question, in terms the person reading it can act on.

Four failures reach a member through the same envelope and mean entirely different things:
they typed something the gateway cannot run, the upstream ran it and refused, the upstream is
not there at all, or we have a bug. Showing all four as "上游没有应答" -- which is what the
page used to do -- tells them to go and find an operator when the fix was in the search box,
and tells the operator nothing when it really was the upstream.

So every failure is classified once, here, and the classification is what both faces of the
service show. Each one carries a short diagnostic that also goes into the log line, so a
member can quote six characters and an operator can find the request.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from knowledge_base.code.upstream import UpstreamRefused, UpstreamUnavailable

logger = logging.getLogger(__name__)


class InvalidQuery(ValueError):
    """The caller asked for something the gateway will not send upstream as it stands."""


class FailureKind(StrEnum):
    """Who has to do something about a failure, which is the only distinction that matters."""

    BAD_REQUEST = "bad_request"
    """The question itself. The member can fix it where they are."""

    REFUSED = "refused"
    """The upstream ran it and said no. A different question might work."""

    UNAVAILABLE = "unavailable"
    """The upstream is not answering. Nothing about the question will help."""

    INTERNAL = "internal"
    """Ours. Nobody outside can do anything except report it."""


@dataclass(frozen=True)
class Trouble:
    """One classified failure, ready to be shown and ready to be looked up."""

    kind: FailureKind
    message: str
    """Chinese, addressed to whoever is looking at the screen."""

    diagnostic: str
    """The same short identifier that was written to the log when this was classified."""


_WORDING: tuple[tuple[type[BaseException], FailureKind, str], ...] = (
    (InvalidQuery, FailureKind.BAD_REQUEST, "检索条件有问题"),
    (UpstreamUnavailable, FailureKind.UNAVAILABLE, "代码域上游暂时不可用"),
    (UpstreamRefused, FailureKind.REFUSED, "上游拒绝了这次查询"),
    (ValueError, FailureKind.BAD_REQUEST, "请求参数有问题"),
)
"""Ordered: the first entry a failure is an instance of decides what it is.

`UpstreamUnavailable` precedes `UpstreamRefused` only because neither is the other's subclass
and the order has to be stated; `ValueError` comes last so a more specific bad request wins.
"""

INTERNAL_WORDING = "网关内部出错"


def classify(failure: BaseException) -> Trouble:
    """Decide what a failure is, record it, and hand back what to show.

    Logging happens here rather than at the call sites so that the diagnostic on the screen
    and the diagnostic in the log are the same one by construction.
    """
    diagnostic = uuid.uuid4().hex[:8]
    for kind, classified, wording in _WORDING:
        if isinstance(failure, kind):
            logger.warning("code request %s failed (%s): %s", diagnostic, classified, failure)
            return Trouble(kind=classified, message=f"{wording}：{failure}", diagnostic=diagnostic)
    logger.error("code request %s failed unexpectedly", diagnostic, exc_info=failure)
    return Trouble(
        kind=FailureKind.INTERNAL,
        message=f"{INTERNAL_WORDING}：{failure}",
        diagnostic=diagnostic,
    )
