"""The code-side tools an agent sees.

The upstream's answers are handed on exactly as they arrived: their shape is not documented,
so reshaping them here would be inventing structure. What is added is the warning that the
call graph has holes, which travels with every answer read off it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from knowledge_base.code.engine import CodeEngine, Direction, SearchMode
from knowledge_base.mcp.progress import answered


@dataclass(frozen=True)
class RepoEntry:
    """One source repository an operator placed under `codebase/`."""

    name: str
    path: str
    indexed: bool
    """Whether the upstream can answer questions about it yet."""


@dataclass(frozen=True)
class RepoList:
    repos: list[RepoEntry] = field(default_factory=list)


@dataclass(frozen=True)
class CodeResult:
    """One answer about code, and what must not be read into it."""

    payload: Any
    caveat: str | None = None


LIST_DESCRIPTION = "列出已纳管的代码库，以及各自是否已建好索引。"

ARCHITECTURE_DESCRIPTION = "某个代码库的整体结构：语言、包、入口、热点。陌生仓库先看这个。"

SEARCH_DESCRIPTION = (
    "在代码库里找代码。mode=symbol 按声明名匹配正则（默认），"
    "mode=text 在源码里搜文本，注释与未解析语言也能搜到。"
)

READ_DESCRIPTION = "按限定名读一个符号的源码，限定名由 search_code 给出。"

TRACE_DESCRIPTION = "沿调用图走：direction=inbound 看谁调用它，outbound 看它调用谁。"

QUERY_DESCRIPTION = (
    "对代码图跑只读 openCypher 查询。仅当上面几个工具都问不出来时才用，它耦合上游的图结构。"
)


def install(server: FastMCP, code: CodeEngine, heartbeat: timedelta) -> None:
    """Register the code-side tools on a server."""

    async def ask(work: Any, context: Context) -> CodeResult:
        answer = await answered(work, context, heartbeat)
        return CodeResult(payload=answer.payload, caveat=answer.caveat)

    @server.tool(description=LIST_DESCRIPTION, annotations={"readOnlyHint": True})
    async def list_repos(context: Context) -> RepoList:
        """Every repository under `codebase/`, and whether it is indexed."""
        repos = await answered(code.list_repos, context, heartbeat)
        return RepoList(
            repos=[
                RepoEntry(name=repo.name, path=repo.path, indexed=repo.indexed) for repo in repos
            ]
        )

    @server.tool(description=ARCHITECTURE_DESCRIPTION, annotations={"readOnlyHint": True})
    async def get_architecture(
        context: Context, repo: Annotated[str, Field(description="代码库名，来自 list_repos")]
    ) -> CodeResult:
        """The shape of one repository."""
        return await ask(lambda: code.get_architecture(repo), context)

    @server.tool(description=SEARCH_DESCRIPTION, annotations={"readOnlyHint": True})
    async def search_code(
        context: Context,
        query: Annotated[str, Field(description="符号名正则，或要搜的文本")],
        mode: Annotated[SearchMode, Field(description="按符号还是按文本")] = SearchMode.SYMBOL,
        repo: Annotated[str | None, Field(description="限定一个代码库，不传则全库")] = None,
    ) -> CodeResult:
        """Find code by declared name, or by text."""
        return await ask(lambda: code.search_code(query, mode=mode, repo=repo), context)

    @server.tool(description=READ_DESCRIPTION, annotations={"readOnlyHint": True})
    async def read_symbol(
        context: Context,
        qualified_name: Annotated[str, Field(description="符号限定名，如 src.copy.DataCopyPad")],
        repo: Annotated[str | None, Field(description="限定一个代码库")] = None,
    ) -> CodeResult:
        """Read the source of one symbol."""
        return await ask(lambda: code.read_symbol(qualified_name, repo=repo), context)

    @server.tool(description=TRACE_DESCRIPTION, annotations={"readOnlyHint": True})
    async def trace_calls(
        context: Context,
        symbol: Annotated[str, Field(description="函数或方法名")],
        direction: Annotated[Direction, Field(description="调用方向")] = Direction.INBOUND,
        depth: Annotated[int, Field(description="最多走几跳", ge=1, le=5)] = 3,
        repo: Annotated[str | None, Field(description="限定一个代码库")] = None,
    ) -> CodeResult:
        """Walk the call graph from a symbol."""
        return await ask(
            lambda: code.trace_calls(symbol, direction=direction, depth=depth, repo=repo), context
        )

    @server.tool(description=QUERY_DESCRIPTION, annotations={"readOnlyHint": True})
    async def query_code_graph(
        context: Context,
        cypher: Annotated[str, Field(description="只读 openCypher 查询")],
        repo: Annotated[str | None, Field(description="限定一个代码库")] = None,
    ) -> CodeResult:
        """Run a read-only graph query, for what the tools above cannot phrase."""
        return await ask(lambda: code.query_code_graph(cypher, repo=repo), context)
