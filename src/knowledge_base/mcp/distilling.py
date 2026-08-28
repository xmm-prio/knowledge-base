"""Distillation: the one way an agent writes to the knowledge base.

Four things can be done to a learning -- write one, add to one, overwrite a conclusion that
has rotted, remove one -- and an agent picks between them by what it passes, not by naming a
mode. That is only safe if the reading is total: every combination of arguments either means
exactly one of the four or is refused with the reason. `_resolve` is that reading, and it is
the whole of the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from knowledge_base.docs.notes import Learning, Observation, Relation
from knowledge_base.docs.service import DocumentService


@dataclass(frozen=True)
class ObservationInput:
    """One fact to write, as an agent phrases it."""

    category: Annotated[str, Field(description="观察的类别，如 pitfall / verified / decision")]
    content: Annotated[str, Field(description="一句话说清的事实")]
    tags: Annotated[list[str], Field(description="这条观察的标签")] = field(default_factory=list)


@dataclass(frozen=True)
class RelationInput:
    """A link to another document, by title. Only meaningful while creating."""

    type: Annotated[str, Field(description="关系类型，如 relates_to")]
    target: Annotated[str, Field(description="目标文档的标题")]


class Mode(StrEnum):
    """What a call to distill_learning turned out to mean."""

    CREATE = "新建"
    APPEND = "追加"
    REVISE = "修订"
    DELETE = "删除"


@dataclass(frozen=True)
class Distilled:
    uri: str
    mode: Mode


@dataclass(frozen=True)
class Request:
    """One call, before it has been read as one of the four modes."""

    author: str
    folder: str | None
    title: str | None
    summary: str | None
    tags: list[str]
    observations: list[ObservationInput]
    relations: list[RelationInput]
    target: str | None
    replaces: str | None
    delete: bool

    @property
    def new_document(self) -> dict[str, object | None]:
        """The arguments a document that does not exist yet cannot do without."""
        return {"folder": self.folder, "title": self.title, "summary": self.summary}

    @property
    def only_when_creating(self) -> dict[str, object | None]:
        """The arguments that describe a document rather than a change to one."""
        return self.new_document | {"relations": self.relations or None}


def _resolve(request: Request) -> Mode:
    """Read a call as one of the four modes, or refuse it saying why."""
    if request.delete:
        if request.target is None:
            raise ToolError("delete=true 需要用 target 指出删除哪条经验")
        if request.replaces or request.observations or _present(request.only_when_creating):
            raise ToolError("delete=true 时只接受 author 与 target")
        return Mode.DELETE

    if request.target is None:
        if request.replaces is not None:
            raise ToolError("replaces 需要与 target 一起传：不传 target 是新建，没有可修订的观察")
        if missing := _missing(request.new_document | {"observations": request.observations}):
            raise ToolError(f"新建经验需要 {'、'.join(missing)}；不传 target 就是新建")
        return Mode.CREATE

    if named := _present(request.only_when_creating):
        raise ToolError(
            f"传了 target 就是在改一条已有经验，{'、'.join(named)} 只在新建时有效；"
            "要另起一篇就不要传 target"
        )
    if not request.observations:
        raise ToolError("追加与修订都需要至少一条 observations")
    if request.replaces is None:
        return Mode.APPEND
    if len(request.observations) != 1:
        raise ToolError("修订需要恰好一条 observations 作为新结论")
    return Mode.REVISE


def _present(arguments: dict[str, object | None]) -> list[str]:
    return [name for name, value in arguments.items() if value]


def _missing(arguments: dict[str, object | None]) -> list[str]:
    return [name for name, value in arguments.items() if not value]


DISTILL_DESCRIPTION = (
    "沉淀一条经验到 learnings/，模式由参数决定："
    "不传 target 为新建（需 folder、title、summary、observations）；"
    "传 target 为向该经验追加 observations；"
    "再传 replaces（要被替换的观察原句）为修订；"
    "传 target 与 delete=true 为删除整条经验。author 填当前使用者的名字。"
)


def install(server: FastMCP, documents: DocumentService) -> None:
    """Register the write tool on a server."""

    @server.tool(description=DISTILL_DESCRIPTION)
    async def distill_learning(
        author: Annotated[str, Field(description="沉淀者，会写进 frontmatter 与 git 历史")],
        folder: Annotated[
            str | None, Field(description="新建时放在 learnings/ 的哪个子目录")
        ] = None,
        title: Annotated[str | None, Field(description="新建时的标题，同时是文件名")] = None,
        summary: Annotated[str | None, Field(description="新建时的一句话结论")] = None,
        observations: Annotated[
            list[ObservationInput] | None, Field(description="要写入的观察")
        ] = None,
        tags: Annotated[list[str] | None, Field(description="新建时的标签")] = None,
        relations: Annotated[
            list[RelationInput] | None, Field(description="新建时指向其他文档的关系")
        ] = None,
        target: Annotated[str | None, Field(description="要改动的经验路径，来自检索结果")] = None,
        replaces: Annotated[str | None, Field(description="要被覆盖的观察原句，逐字")] = None,
        delete: Annotated[bool, Field(description="删除 target 指向的整条经验")] = False,
    ) -> Distilled:
        """Write, extend, revise or remove one learning."""
        request = Request(
            author=author,
            folder=folder,
            title=title,
            summary=summary,
            tags=tags or [],
            observations=observations or [],
            relations=relations or [],
            target=target,
            replaces=replaces,
            delete=delete,
        )
        mode = _resolve(request)
        return Distilled(uri=await _apply(documents, request, mode), mode=mode)


async def _apply(documents: DocumentService, request: Request, mode: Mode) -> str:
    """Carry out a request that has already been read as one mode."""
    target = str(request.target)
    match mode:
        case Mode.CREATE:
            return await documents.create_learning(str(request.folder), _learning(request))
        case Mode.APPEND:
            return await documents.append_to_learning(
                target, request.author, _observations(request)
            )
        case Mode.REVISE:
            return await documents.revise_learning(
                target, request.author, str(request.replaces), _observations(request)[0]
            )
        case Mode.DELETE:
            await documents.delete_learning(target, request.author)
            return target


def _learning(request: Request) -> Learning:
    return Learning(
        title=str(request.title),
        summary=str(request.summary),
        tags=request.tags,
        author=request.author,
        observations=_observations(request),
        relations=[Relation(type=r.type, target=r.target) for r in request.relations],
    )


def _observations(request: Request) -> list[Observation]:
    return [
        Observation(category=o.category, content=o.content, tags=o.tags)
        for o in request.observations
    ]
