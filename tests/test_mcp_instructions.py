"""Tests for what an agent is told the moment it connects.

Every member pays for this text in every session, so it is asserted on twice: that it says
enough for an agent to decide whether searching is worth a call, and that it stays small.
"""

import json
import re
from pathlib import Path

import httpx
import pytest

from conftest import ManualSleep
from knowledge_base.code.engine import CodeEngine
from knowledge_base.docs.notes import Learning, Observation
from knowledge_base.docs.service import DocumentService
from knowledge_base.layout import KnowledgeBaseRoot
from knowledge_base.mcp import create_mcp_app
from knowledge_base.mcp.instructions import Snapshot, compose, outline, survey
from mcp_harness import StubUpstream

TOKEN_BUDGET = 400
"""The outline is meant to be about 300 tokens; this is that, with room to breathe."""


def estimated_tokens(text: str) -> int:
    """A deliberately crude count: one token per Han character, one per Latin word.

    Tokenizers differ, but not by enough to matter when the question is whether a paragraph
    is a paragraph or an essay.
    """
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_./-]+", text))
    return han + latin


FULL = Snapshot(
    documents=128,
    knowledge_folders=("ascendc", "流程"),
    repos=("mops", "ascendc-samples"),
    tags=tuple((f"标签{n}", 30 - n) for n in range(20)),
)


class TestTheOutline:
    def test_it_says_what_each_of_the_three_directories_is_for(self) -> None:
        written = outline(FULL)

        assert "knowledge/" in written
        assert "learnings/" in written
        assert "codebase/" in written

    def test_it_lists_the_top_level_subjects_and_the_indexed_repos(self) -> None:
        written = outline(FULL)

        assert "ascendc" in written and "流程" in written
        assert "mops" in written

    def test_it_says_how_much_there_is(self) -> None:
        assert "128" in outline(FULL)

    def test_it_fits_the_budget_it_is_paid_for_out_of(self) -> None:
        assert estimated_tokens(outline(FULL)) <= TOKEN_BUDGET

    def test_an_empty_knowledge_base_still_reads_as_a_sentence(self) -> None:
        written = outline(Snapshot())

        assert "（暂无）" in written
        assert "0 篇文档" in written


class TestTheStaticHalf:
    def test_it_says_when_to_search_when_to_distil_and_what_author_means(self) -> None:
        written = compose(Snapshot())

        assert "search_knowledge" in written
        assert "distill_learning" in written
        assert "author" in written


async def test_the_survey_reads_the_library_rather_than_being_told_about_it(
    tmp_path: Path,
) -> None:
    root = KnowledgeBaseRoot(tmp_path)
    root.initialize()
    (root.knowledge_dir / "ascendc").mkdir()
    (root.knowledge_dir / "ascendc" / "概览.md").write_text(
        "---\ntags: [ascendc]\n---\n\n# 概览\n", encoding="utf-8"
    )
    (root.codebase_dir / "mops").mkdir()
    upstream = StubUpstream({"list_projects": {"projects": [{"name": "mops"}]}})
    documents = DocumentService(root, sleep=ManualSleep())
    await documents.start()
    try:
        await documents.create_learning(
            "ascendc",
            Learning(
                title="对齐要求",
                summary="尾块会读到脏数据",
                tags=["ascendc", "datacopy"],
                author="dyq",
                observations=[Observation("pitfall", "尾块会读到脏数据")],
            ),
        )
    finally:
        await documents.stop()

    snapshot = survey(root, CodeEngine(root, upstream))

    assert snapshot.documents == 2
    assert snapshot.knowledge_folders == ("ascendc",)
    assert snapshot.repos == ("mops",)
    assert snapshot.tags == (("ascendc", 2), ("datacopy", 1))


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


async def connect(app: object) -> dict[str, object]:
    """Do the one exchange opencode does before anything else, and read the answer."""
    transport = httpx.ASGITransport(app=app)  # pyright: ignore[reportArgumentType]
    async with httpx.AsyncClient(transport=transport, base_url="http://kb.internal") as client:
        response = await client.post(
            "/mcp",
            json=INITIALIZE,
            headers={"accept": "application/json, text/event-stream"},
        )
    body = response.text
    payload = body.split("data:", 1)[1] if "data:" in body else body
    return json.loads(payload)["result"]


@pytest.mark.asyncio
async def test_the_outline_is_generated_for_each_connection(tmp_path: Path) -> None:
    """A knowledge base grows while the service runs; an outline built at startup goes stale."""
    root = KnowledgeBaseRoot(tmp_path)
    root.initialize()
    documents = DocumentService(root, sleep=ManualSleep())
    await documents.start()
    app = create_mcp_app(root, documents, CodeEngine(root, StubUpstream()))
    try:
        async with app.router.lifespan_context(app):
            (root.knowledge_dir / "新分类").mkdir()

            result = await connect(app)

            assert "新分类" in str(result["instructions"])
    finally:
        await documents.stop()
