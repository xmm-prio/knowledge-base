"""The relation graph of the knowledge base.

basic-memory is mounted in-process -- its FastAPI app over an ASGI transport, no subprocess
and no socket -- and is used for one thing only: which document points at which, and how.
Retrieval belongs to the gateway's own index (ADR-0006), so its search is never called.

Everything crossing this boundary is named the way the rest of the system names it: paths
relative to the knowledge base root. Upstream's permalinks, project UUIDs and entity ids stay
inside.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from knowledge_base.docs.store import MARKDOWN_SUFFIX, NoSuchDocument
from knowledge_base.layout import KnowledgeBaseRoot

__all__ = [
    "DocumentGraph",
    "GraphUnavailable",
    "Link",
    "LinkedDocument",
    "Neighbourhood",
    "NoSuchDocument",
]

BASE_URL = "http://basic-memory.internal"

CONFIG_DIR_VARIABLE = "BASIC_MEMORY_CONFIG_DIR"
HOME_VARIABLE = "BASIC_MEMORY_HOME"
SEMANTIC_SEARCH_VARIABLE = "BASIC_MEMORY_SEMANTIC_SEARCH_ENABLED"
LOGFIRE_VARIABLE = "LOGFIRE_IGNORE_NO_CONFIG"


class GraphUnavailable(RuntimeError):
    """basic-memory answered with something the gateway cannot use."""


@dataclass(frozen=True)
class LinkedDocument:
    """A document reachable from the one being explored."""

    path: str
    title: str


@dataclass(frozen=True)
class Link:
    """A relation as it was written, from the document that holds the line."""

    type: str
    source: str
    target: str
    """Empty while the target has not been written yet."""

    target_name: str


@dataclass(frozen=True)
class Neighbourhood:
    """What surrounds one document in the graph, out to some number of steps."""

    origin: str
    documents: tuple[LinkedDocument, ...]
    links: tuple[Link, ...]


class DocumentGraph:
    """basic-memory, mounted in-process, asked only about relations."""

    def __init__(self, root: KnowledgeBaseRoot) -> None:
        self._root = root
        self._client: httpx.AsyncClient | None = None
        self._application: Any = None
        self._lifespan: Any = None
        self._project: str = ""

    async def start(self) -> None:
        """Bring the upstream app up inside this process."""
        if self._client is not None:
            return
        self._redirect_upstream()

        from basic_memory.api.app import app

        self._application = app
        self._lifespan = app.router.lifespan_context(app)
        await self._lifespan.__aenter__()
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE_URL, timeout=None
        )
        self._project = await self._sole_project()

    async def stop(self) -> None:
        if self._client is None:
            return
        client, lifespan = self._client, self._lifespan
        self._client, self._lifespan, self._application = None, None, None
        await client.aclose()
        await lifespan.__aexit__(None, None, None)

    async def reindex(self) -> int:
        """Read every document again and rebuild the graph. Returns how many were taken in."""
        response = await self._request(
            "POST",
            f"/v2/projects/{self._project}/index",
            params={"force_full": True, "run_in_background": False},
        )
        await self._settle()
        return int(response.get("total_files", 0))

    async def neighbourhood(self, relative_path: str, depth: int = 1) -> Neighbourhood:
        """The documents within `depth` relations of this one, and the relations joining them."""
        body = await self._request(
            "GET",
            f"/v2/projects/{self._project}/memory/{_as_uri(relative_path)}",
            params={"depth": depth, "max_related": 100},
        )
        results = body.get("results") or []
        if not results:
            raise NoSuchDocument(f"no document at {relative_path}")

        # The same entity comes back both as a result of its own and as a neighbour of
        # another, so everything is gathered into ordered sets before being shaped.
        paths: dict[str, str] = {}
        entities: dict[str, str] = {}
        relations: list[dict[str, Any]] = []
        for item in _flatten(results):
            if item["type"] == "entity":
                entities[item["external_id"]] = item["file_path"]
                paths.setdefault(item["file_path"], item["title"])
            elif item["type"] == "relation":
                relations.append(item)

        links = {
            Link(
                type=relation["relation_type"],
                source=relation["file_path"],
                target=entities.get(relation.get("to_entity_external_id") or "", ""),
                target_name=relation.get("to_name") or "",
            ): None
            for relation in relations
        }
        neighbours = tuple(
            LinkedDocument(path=path, title=title)
            for path, title in paths.items()
            if path != relative_path
        )
        return Neighbourhood(origin=relative_path, documents=neighbours, links=tuple(links))

    def _redirect_upstream(self) -> None:
        """Upstream reads its own configuration from the environment, so this is the only
        handle there is on where it keeps its data."""
        configuration = self._root.basic_memory_dir
        configuration.mkdir(parents=True, exist_ok=True)
        os.environ[CONFIG_DIR_VARIABLE] = str(configuration)
        # A single project at the root, so learnings can link to knowledge (ADR-0004).
        os.environ[HOME_VARIABLE] = str(self._root.path)
        # Semantic search would download an embedding model on first use, and the gateway
        # never asks upstream to search (ADR-0006).
        os.environ[SEMANTIC_SEARCH_VARIABLE] = "false"
        # Upstream instruments itself with Logfire, which warns on every span while no
        # telemetry backend is configured. The gateway does not configure one.
        os.environ.setdefault(LOGFIRE_VARIABLE, "1")

    async def _sole_project(self) -> str:
        body = await self._request("GET", "/v2/projects/")
        projects = body.get("projects") or []
        if len(projects) != 1:
            raise GraphUnavailable(f"expected one project at the root, found {len(projects)}")
        return str(projects[0]["external_id"])

    async def _settle(self) -> None:
        """Indexing hands the tail of its work to background tasks; wait them out so a caller
        that reindexes and then reads sees what it just indexed."""
        from basic_memory.index.local_schedulers import drain_background_tasks

        await drain_background_tasks()

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if self._client is None:
            raise GraphUnavailable("the document graph has not been started")
        response = await self._client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise GraphUnavailable(f"{method} {url} returned {response.status_code}")
        return response.json()


def _as_uri(relative_path: str) -> str:
    """Upstream addresses a document by its path without the extension."""
    return relative_path.removesuffix(MARKDOWN_SUFFIX)


def _flatten(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entity can come back as its own result and as another's neighbour."""
    items: list[dict[str, Any]] = []
    for result in results:
        items.append(result["primary_result"])
        items += list(result.get("related_results") or [])
    return items
