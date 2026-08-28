"""What every route is handed: the two domains, already built and already running."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request

from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.service import DocumentService


class UpstreamHealth(Protocol):
    """Whatever can say if the code domain's upstream is answering. The supervisor is one."""

    def check_health(self) -> bool: ...


@dataclass(frozen=True)
class Domains:
    """The two domains this API is a face for."""

    documents: DocumentService
    code: CodeEngine

    supervisor: UpstreamHealth | None = None
    """Absent when nothing supervises the upstream, in which case its health is reported as
    unknown rather than guessed at."""


def domains(request: Request) -> Domains:
    return request.app.state.domains


Bound = Annotated[Domains, Depends(domains)]
"""What a route declares in order to be handed the domains."""
