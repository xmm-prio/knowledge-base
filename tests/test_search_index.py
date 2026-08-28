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
