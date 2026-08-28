"""The command line an operator uses on the server.

Four things an operator ever does: create a knowledge base, run it, rebuild an index that has
drifted, and ask what state it is in. Everything below builds the same `Service` the running
process is; the one-shot commands just drive its lifecycle themselves instead of leaving it to
uvicorn.
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
from knowledge_base.api.system import opencode_config
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.server import MCP_PATH, Service

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

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


def _offline[T](root: Path, work: Callable[[Service], Awaitable[T]]) -> T:
    """Run one piece of work against a fully started service, then shut it down again.

    The same assembly the server runs, so a reindex from the command line sees exactly what
    the running service would see -- including a flushed commit on the way out.

    Driven by anyio rather than `asyncio.run`, because the upstream document graph reaches
    for anyio's worker threads and those are only released when anyio owns the loop. Under
    `asyncio.run` they are left behind as non-daemon threads and the command never exits.
    """

    async def run() -> T:
        service = Service(_root(root))
        await service.start()
        try:
            return await work(service)
        finally:
            await service.stop()

    return anyio.run(run)


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
    service = Service(_root(root), frontend=frontend)
    reachable = "localhost" if host in ("0.0.0.0", "::") else host
    logger.info("knowledge-base %s", __version__)
    logger.info("Knowledge base root: %s", service.root.path)
    logger.info("Listening on http://%s:%d", host, port)
    logger.info("MCP endpoint: http://%s:%d%s", reachable, port, MCP_PATH)
    uvicorn.run(service.application, host=host, port=port, log_config=None)


@reindex.command("documents", help="重建文档检索索引与知识图谱")
def reindex_documents(root: Root = Path(), verbose: Verbose = False) -> None:
    _configure_logging(verbose)
    indexed = _offline(root, lambda service: service.documents.rebuild())
    typer.echo(f"已索引 {indexed} 篇文档")


@reindex.command("code", help="重建代码库索引；不指定 --repo 则重建全部")
def reindex_code(root: Root = Path(), repo: Repo = None, verbose: Verbose = False) -> None:
    _configure_logging(verbose)

    async def rebuild(service: Service) -> list[tuple[str, bool]]:
        if repo is not None:
            one = await asyncio.to_thread(service.code.rebuild, repo)
            return [(one.repo, one.ok)]
        every = await asyncio.to_thread(lambda: list(service.code.rebuild_all()))
        return [(outcome.repo, outcome.ok) for outcome in every]

    outcomes = _offline(root, rebuild)
    if not outcomes:
        typer.echo("codebase/ 下没有代码库")
    for name, ok in outcomes:
        typer.echo(f"{name}: {'已索引' if ok else '失败'}")


@app.command(help="打印索引规模、上游状态与组员要用的 opencode 接入片段")
def status(root: Root = Path(), host: Host = DEFAULT_HOST, port: Port = DEFAULT_PORT) -> None:
    _configure_logging()

    async def look(service: Service) -> tuple[int, int, bool, int, int]:
        size = await service.documents.size()
        repos = await asyncio.to_thread(service.code.list_repos)
        return (
            size.documents,
            size.observations,
            service.upstream.running,
            len(repos),
            sum(1 for one in repos if one.indexed),
        )

    documents, observations, upstream, repos, indexed = _offline(root, look)
    reachable = "localhost" if host in ("0.0.0.0", "::") else host
    url = f"http://{reachable}:{port}{MCP_PATH}"
    typer.echo(f"根目录：{_root(root).path}")
    typer.echo(f"文档：{documents} 篇，观察 {observations} 条")
    typer.echo(f"代码域上游：{'已连接' if upstream else '不可用'}")
    typer.echo(f"代码库：{repos} 个，其中 {indexed} 个已索引")
    typer.echo("组员的 opencode 配置片段：")
    typer.echo(opencode_config(url))
