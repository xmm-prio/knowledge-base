"""Tests for the gateway-owned search index.

The reason this index exists at all is Chinese retrieval (see ADR-0006), so the tests are
written around terms that sit in the middle of a Chinese sentence -- exactly what upstream's
tokenizer cannot reach.
"""

from pathlib import Path

import pytest

from knowledge_base.docs.documents import Document
from knowledge_base.docs.notes import Observation
from knowledge_base.docs.search_index import SearchIndex


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    return SearchIndex(tmp_path / "search.db")


def doc(path: str, body: str = "", **kwargs) -> Document:
    return Document(
        path=path,
        title=kwargs.pop("title", path),
        summary=kwargs.pop("summary", ""),
        tags=kwargs.pop("tags", []),
        body=body,
        observations=kwargs.pop("observations", []),
    )


def paths(hits) -> list[str]:
    return sorted({hit.path for hit in hits})


def test_a_term_in_the_middle_of_a_chinese_sentence_is_found(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", body="非对齐搬运时会读到脏数据，需要先做 padding。"))

    assert paths(index.search("脏数据")) == ["learnings/a.md"]


def test_one_query_reaches_every_document_that_discusses_the_term(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", body="blockLen 非 32B 对齐时尾部会读到脏数据。"))
    index.put(doc("learnings/b.md", body="非对齐搬运时会读到脏数据。"))
    index.put(doc("knowledge/c.md", body="搬运前必须检查 UB 地址对齐。"))
    index.put(doc("knowledge/d.md", body="TQue 的双缓冲深度设为 2 时流水最稳。"))

    assert paths(index.search("对齐")) == ["knowledge/c.md", "learnings/a.md", "learnings/b.md"]


def test_an_english_identifier_still_matches_exactly(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", body="调用 DataCopyPad(dst, src, padParams) 处理尾块。"))

    assert paths(index.search("DataCopyPad")) == ["learnings/a.md"]


def test_a_document_is_found_by_its_title_and_summary(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", title="DataCopy 的对齐要求", summary="尾块会读到脏数据"))

    assert paths(index.search("对齐要求")) == ["learnings/a.md"]
    assert paths(index.search("尾块")) == ["learnings/a.md"]


def test_rewriting_a_document_replaces_what_was_indexed(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", body="双缓冲深度设为 2"))
    index.put(doc("learnings/a.md", body="双缓冲深度改为 4"))

    assert paths(index.search("双缓冲")) == ["learnings/a.md"]
    assert index.search("设为") == []


def test_removing_a_document_takes_it_out_of_the_index(index: SearchIndex) -> None:
    index.put(doc("learnings/a.md", body="双缓冲深度设为 2"))

    index.remove("learnings/a.md")

    assert index.search("双缓冲") == []


def test_an_observation_is_a_hit_of_its_own(index: SearchIndex) -> None:
    """Progressive disclosure hands back the matching observation, not the whole file."""
    index.put(
        doc(
            "learnings/a.md",
            title="DataCopy 的对齐要求",
            observations=[
                Observation("pitfall", "非对齐搬运时会读到脏数据", ["对齐"]),
                Observation("verified", "改用 DataCopyPad 后尾块正确"),
            ],
        )
    )

    hits = index.search("脏数据")

    assert [(h.kind, h.snippet) for h in hits] == [("observation", "非对齐搬运时会读到脏数据")]


class TestListing:
    """The directory tree and the tag cloud read the index rather than the disk: it already
    knows every document's title, and re-parsing the whole corpus per page view would not."""

    def test_it_lists_every_indexed_document_by_path(self, index: SearchIndex) -> None:
        index.put(doc("learnings/b.md", title="乙"))
        index.put(doc("knowledge/a.md", title="甲", summary="一句话"))

        listing = index.documents()

        assert [(d.path, d.title, d.summary) for d in listing] == [
            ("knowledge/a.md", "甲", "一句话"),
            ("learnings/b.md", "乙", ""),
        ]

    def test_a_listed_document_carries_its_tags(self, index: SearchIndex) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc", "datacopy"]))

        assert index.documents()[0].tags == ["ascendc", "datacopy"]

    def test_it_can_be_narrowed_to_one_tag(self, index: SearchIndex) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc"]))
        index.put(doc("learnings/b.md", tags=["mops"]))

        assert [d.path for d in index.documents(tag="ascendc")] == ["learnings/a.md"]

    def test_a_document_appears_once_however_many_observations_it_holds(
        self, index: SearchIndex
    ) -> None:
        index.put(
            doc(
                "learnings/a.md",
                observations=[Observation("pitfall", "甲"), Observation("verified", "乙")],
            )
        )

        assert [d.path for d in index.documents()] == ["learnings/a.md"]


class TestTagCloud:
    def test_it_counts_how_many_documents_carry_each_tag(self, index: SearchIndex) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc", "datacopy"]))
        index.put(doc("learnings/b.md", tags=["ascendc"]))

        assert [(t.tag, t.count) for t in index.tag_counts()] == [("ascendc", 2), ("datacopy", 1)]

    def test_rewriting_a_document_does_not_leave_its_old_tags_behind(
        self, index: SearchIndex
    ) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc"]))
        index.put(doc("learnings/a.md", tags=["mops"]))

        assert [t.tag for t in index.tag_counts()] == ["mops"]

    def test_removing_a_document_takes_its_tags_with_it(self, index: SearchIndex) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc"]))

        index.remove("learnings/a.md")

        assert index.tag_counts() == []


class TestSize:
    """The system status page reports how much has actually been indexed."""

    def test_it_reports_documents_observations_and_distinct_tags(self, index: SearchIndex) -> None:
        index.put(
            doc(
                "learnings/a.md",
                tags=["ascendc"],
                observations=[Observation("pitfall", "甲"), Observation("verified", "乙")],
            )
        )
        index.put(doc("knowledge/b.md", tags=["ascendc", "mops"]))

        size = index.size()

        assert (size.documents, size.observations, size.tags) == (2, 2, 2)

    def test_an_empty_index_reports_zeroes(self, index: SearchIndex) -> None:
        size = index.size()

        assert (size.documents, size.observations, size.tags) == (0, 0, 0)

    def test_clearing_the_index_clears_the_tags_too(self, index: SearchIndex) -> None:
        index.put(doc("learnings/a.md", tags=["ascendc"]))

        index.clear()

        assert index.tag_counts() == []
        assert index.size().documents == 0
