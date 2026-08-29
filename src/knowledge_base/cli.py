"""The command line an operator uses on the server.

Four things an operator ever does: create a knowledge base, run it, rebuild an index that has
drifted, and ask what state it is in.

`server` builds the whole `Service` and hands its lifecycle to uvicorn. The one-shot commands
bring up only the domain they touch: rebuilding a code index has no reason to start the
document graph, which costs several seconds of migrations, and no reason to hold the upstream's
per-account cache while doing it (ADR-0007).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

import anyio
import typer
import uvicorn

from knowledge_base import __version__
from knowledge_base.address import DEFAULT_PORT, Address, NoRouteOutward, advertised_for
from knowledge_base.api.system import opencode_config
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.server import MCP_PATH, Service, code_domain, document_domain

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

app = typer.Typer(help="内部知识库服务", no_args_is_help=True, add_completion=False)
reindex = typer.Typer(help="重建索引", no_args_is_help=True)
app.add_typer(reindex, name="reindex")

Root = Annotated[Path, typer.Option("--root", help="知识库根目录", show_default=".")]
Host = Annotated[str, typer.Option("--host", help="监听地址")]
Port = Annotated[int, typer.Option("--port", help="监听端口")]
Repo = Annotated[str | None, typer.Option("--repo", help="只重建这一个代码库")]
Verbose = Annotated[bool, typer.Option("--verbose", help="打印调试日志")]
Frontend = Annotated[
    Path | None,
    typer.Option(
        "--frontend",
        envvar="KB_FRONTEND_DIST",
        help="网页 UI 构建产物目录，默认取源码树里的 frontend/dist",
    ),
]


def _configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format=LOG_FORMAT, force=True
    )


def _root(path: Path) -> KnowledgeBaseRoot:
    return KnowledgeBaseRoot(path.resolve())


def _announced(address: Address) -> str:
    """The MCP endpoint as the startup log should state it, or why it cannot be stated."""
    try:
        return address.advertised().url(MCP_PATH)
    except NoRouteOutward as unknown:
        return str(unknown)


def _offline[T](work: Callable[[], Awaitable[T]]) -> T:
    """Run one piece of asynchronous work to completion, and get the process back.

    Driven by anyio rather than `asyncio.run`, because the upstream document graph reaches
    for anyio's worker threads and those are only released when anyio owns the loop. Under
    `asyncio.run` they are left behind as non-daemon threads and the command never exits.
    """
    return anyio.run(work)


@app.command(help="只初始化知识库根目录的布局，不启动服务")
def init(root: Root = Path(), verbose: Verbose = False) -> None:
    _configure_logging(verbose)
    here = _root(root)
    here.initialize()
    logger.info("Knowledge base ready at %s", here.path)
    typer.echo(f"已初始化：{here.path}")


@app.command(help="在知识库根目录上启动服务：网页 UI、REST API 与 MCP 端点")
def server(
    root: Root = Path(),
    host: Host = DEFAULT_HOST,
    port: Port = DEFAULT_PORT,
    frontend: Frontend = None,
    verbose: Verbose = False,
) -> None:
    _configure_logging(verbose)
    address = advertised_for(host, port)
    service = Service(_root(root), frontend=frontend, address=address)
    logger.info("knowledge-base %s", __version__)
    logger.info("Knowledge base root: %s", service.root.path)
    logger.info("Listening on http://%s:%d", host, port)
    logger.info("MCP endpoint: %s", _announced(address))
    logger.info(
        "There is no authentication in front of this: it is meant for a network where "
        "everyone who can reach it is allowed to read and write."
    )
    uvicorn.run(service.application, host=host, port=port, log_config=None)


@reindex.command("documents", help="重建文档检索索引与知识图谱")
def reindex_documents(root: Root = Path(), verbose: Verbose = False) -> None:
    _configure_logging(verbose)

    async def rebuild() -> int:
        # Entering the domain is the rebuild: reading every document in is what starting it means.
        async with document_domain(_root(root)) as documents:
            return (await documents.size()).documents

    typer.echo(f"已索引 {_offline(rebuild)} 篇文档")


@reindex.command("code", help="重建代码库索引；不指定 --repo 则重建全部")
def reindex_code(root: Root = Path(), repo: Repo = None, verbose: Verbose = False) -> None:
    _configure_logging(verbose)

    async def rebuild() -> list[tuple[str, bool]]:
        async with code_domain(_root(root)) as code:
            if repo is not None:
                one = await asyncio.to_thread(code.engine.rebuild, repo)
                return [(one.repo, one.ok)]
            every = await asyncio.to_thread(lambda: list(code.engine.rebuild_all()))
            return [(outcome.repo, outcome.ok) for outcome in every]

    outcomes = _offline(rebuild)
    if not outcomes:
        typer.echo("codebase/ 下没有代码库")
    for name, ok in outcomes:
        typer.echo(f"{name}: {'已索引' if ok else '失败'}")


@app.command(help="打印索引规模、上游状态与组员要用的 opencode 接入片段")
def status(root: Root = Path(), host: Host = DEFAULT_HOST, port: Port = DEFAULT_PORT) -> None:
    _configure_logging()

    async def look() -> tuple[int, int, bool, int, int]:
        async with document_domain(_root(root)) as documents:
            size = await documents.size()
        async with code_domain(_root(root)) as code:
            repos = await asyncio.to_thread(code.engine.list_repos)
            reachable = code.upstream.running
        return (
            size.documents,
            size.observations,
            reachable,
            len(repos),
            sum(1 for one in repos if one.indexed),
        )

    documents, observations, upstream, repos, indexed = _offline(look)
    typer.echo(f"根目录：{_root(root).path}")
    typer.echo(f"文档：{documents} 篇，观察 {observations} 条")
    typer.echo(f"代码域上游：{'已连接' if upstream else '不可用'}")
    typer.echo(f"代码库：{repos} 个，其中 {indexed} 个已索引")
    try:
        url = advertised_for(host, port).advertised().url(MCP_PATH)
    except NoRouteOutward as unknown:
        typer.echo(f"MCP 地址：{unknown}")
        return
    typer.echo("组员的 opencode 配置片段：")
    typer.echo(opencode_config(url))
