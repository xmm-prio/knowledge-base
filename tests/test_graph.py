"""Tests for the relation graph.

Retrieval is the gateway's own (ADR-0006); what basic-memory is still here for is the graph:
which document points at which, and how. This is the seam `explore_links` sits on.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from knowledge_base.docs.graph import DocumentGraph, Link, NoSuchDocument
from knowledge_base.layout import KnowledgeBaseRoot

LAYOUT = "knowledge/UB 内存布局.md"
OVERVIEW = "knowledge/搬运 API 概览.md"
LEARNING = "learnings/ascendc/DataCopy 的对齐要求.md"

DOCUMENTS = {
    LAYOUT: "---\ntitle: UB 内存布局\n---\n\n# UB 内存布局\n",
    OVERVIEW: (
        "---\ntitle: 搬运 API 概览\n---\n\n# 搬运 API 概览\n\n"
        "## Relations\n- relates_to [[UB 内存布局]]\n"
    ),
    LEARNING: (
        "---\ntitle: DataCopy 的对齐要求\n---\n\n# DataCopy 的对齐要求\n\n"
        "## Observations\n- [pitfall] 非对齐尾块会读到脏数据\n\n"
        "## Relations\n- relates_to [[搬运 API 概览]]\n- supersedes [[尚未沉淀的经验]]\n"
    ),
}


# Standing basic-memory up costs a second or two, and nothing here writes a document, so the
# whole module shares one knowledge base and one event loop.
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def graph(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[DocumentGraph]:
    base = tmp_path_factory.mktemp("knowledge-base")
    root = KnowledgeBaseRoot(base)
    root.initialize()
    for relative, text in DOCUMENTS.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    document_graph = DocumentGraph(root)
    await document_graph.start()
    await document_graph.reindex()
    try:
        yield document_graph
    finally:
        await document_graph.stop()


class TestReindex:
    async def test_it_counts_the_documents_it_took_in(self, graph: DocumentGraph) -> None:
        assert await graph.reindex() == len(DOCUMENTS)


class TestNeighbourhood:
    async def test_it_finds_the_knowledge_a_learning_points_at(self, graph: DocumentGraph) -> None:
        neighbourhood = await graph.neighbourhood(LEARNING)

        assert [document.path for document in neighbourhood.documents] == [OVERVIEW]

    async def test_it_carries_the_title_of_each_neighbour(self, graph: DocumentGraph) -> None:
        neighbourhood = await graph.neighbourhood(LEARNING)

        assert [document.title for document in neighbourhood.documents] == ["搬运 API 概览"]

    async def test_it_finds_the_learnings_that_point_at_a_piece_of_knowledge(
        self, graph: DocumentGraph
    ) -> None:
        """Links are written on one side only, but they are worth following from both."""
        neighbourhood = await graph.neighbourhood(OVERVIEW)

        assert LEARNING in [document.path for document in neighbourhood.documents]

    async def test_it_says_what_kind_of_relation_joins_two_documents(
        self, graph: DocumentGraph
    ) -> None:
        neighbourhood = await graph.neighbourhood(LEARNING)

        assert (
            Link(type="relates_to", source=LEARNING, target=OVERVIEW, target_name="搬运 API 概览")
            in neighbourhood.links
        )

    async def test_it_keeps_a_relation_whose_target_has_not_been_written_yet(
        self, graph: DocumentGraph
    ) -> None:
        """An agent may link to a learning nobody has distilled; the intent is still worth
        showing rather than dropping."""
        neighbourhood = await graph.neighbourhood(LEARNING)

        assert (
            Link(type="supersedes", source=LEARNING, target="", target_name="尚未沉淀的经验")
            in neighbourhood.links
        )

    async def test_it_reaches_past_the_first_step_when_asked(self, graph: DocumentGraph) -> None:
        neighbourhood = await graph.neighbourhood(LEARNING, depth=2)

        assert LAYOUT in [document.path for document in neighbourhood.documents]

    async def test_it_leaves_the_document_it_started_from_out_of_its_neighbours(
        self, graph: DocumentGraph
    ) -> None:
        neighbourhood = await graph.neighbourhood(LEARNING, depth=2)

        assert LEARNING not in [document.path for document in neighbourhood.documents]

    async def test_it_refuses_a_document_that_is_not_in_the_knowledge_base(
        self, graph: DocumentGraph
    ) -> None:
        with pytest.raises(NoSuchDocument):
            await graph.neighbourhood("learnings/从来没有写过.md")
