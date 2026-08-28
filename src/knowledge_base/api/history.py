"""Version history over HTTP, and the one way back.

git is the version mechanism (ADR-0003), so this is a reading of git rather than of a
snapshot table of our own.

Rollback is the only destructive thing the web UI can do, and it is deliberately narrow:

- one document at a time. A commit here aggregates whatever one author happened to write
  during a quiet period, across unrelated documents, so "undo this commit" would undo things
  the person looking at one document's history never saw.
- it moves forwards. The text a revision held is written again as a new commit; nothing in
  history is rewritten, so a rollback is itself something you can roll back.
- it refuses rather than guesses. A revision that held no such document is a 404, not a
  deletion.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from knowledge_base.api.dependencies import Bound
from knowledge_base.vcs import DEFAULT_LOG_LENGTH, Revision

router = APIRouter(prefix="/history", tags=["history"])

MAX_LOG_LENGTH = 200


class RevisionReply(BaseModel):
    """One commit, as the history page lists it."""

    revision: str
    """The full object name; short ones stop being unique as a history grows."""

    author: str
    message: str
    at: str
    """The author date, ISO-8601 with an offset."""


class HistoryReply(BaseModel):
    path: str | None
    """The document this history was narrowed to, or null for the whole knowledge base."""

    revisions: list[RevisionReply]


class CommitReply(BaseModel):
    revision: str
    paths: list[str]
    """Every document the commit touched -- a quiet period's worth, not necessarily one."""


class RevisionTextReply(BaseModel):
    path: str
    revision: str
    text: str
    """The raw Markdown as it stood at that revision, for a diff or a preview."""


class RestoreRequest(BaseModel):
    """Put one document back to the text one revision held."""

    path: str
    author: str = Field(min_length=1, description="谁回滚的；回滚会以其名义产生一个新提交")


class RestoreReply(BaseModel):
    path: str
    restored_from: str
    """The revision the text came from."""

    revision: str | None
    """The commit the rollback made, or null when the document already held that text."""


def revision(one: Revision) -> RevisionReply:
    return RevisionReply(revision=one.revision, author=one.author, message=one.message, at=one.at)


@router.get("", summary="git 历史；可按文档收窄")
async def history(
    bound: Bound,
    path: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LOG_LENGTH)] = DEFAULT_LOG_LENGTH,
) -> HistoryReply:
    found = await bound.documents.history(path, limit=limit)
    return HistoryReply(path=path, revisions=[revision(one) for one in found])


@router.get("/{name}/document", summary="读一篇文档在某个提交时的原文")
async def document_at(
    name: str, bound: Bound, path: Annotated[str, Query(min_length=1)]
) -> RevisionTextReply:
    return RevisionTextReply(
        path=path, revision=name, text=await bound.documents.revision_text(path, name)
    )


@router.post("/{name}/restore", summary="把一篇文档回滚到某个提交的内容")
async def restore(name: str, request: RestoreRequest, bound: Bound) -> RestoreReply:
    made = await bound.documents.restore(request.path, name, request.author)
    return RestoreReply(path=request.path, restored_from=name, revision=made)


@router.get("/{name}", summary="一个提交动了哪些文档")
async def commit(name: str, bound: Bound) -> CommitReply:
    return CommitReply(revision=name, paths=await bound.documents.paths_in(name))
