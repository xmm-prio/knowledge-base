"""Tests for semantic Markdown rendering and parsing.

The expected values come from basic-memory's own parser, not from our renderer's logic:
if upstream cannot read back what we wrote, the document is not indexable no matter how
reasonable it looks.
"""

import frontmatter
import pytest
from basic_memory.markdown.entity_parser import parse as upstream_parse

from knowledge_base.docs.notes import (
    Learning,
    Observation,
    Relation,
    parse_learning,
    render_learning,
)


def _upstream(text: str):
    """Read a rendered document back with basic-memory's parser."""
    return upstream_parse(frontmatter.parse(text)[1])


def test_rendered_observation_is_read_back_by_upstream() -> None:
    learning = Learning(
        title="DataCopy 的对齐要求",
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["ascendc", "datacopy"],
        author="dyq",
        observations=[
            Observation(
                category="pitfall",
                content="blockLen 非 32B 对齐时尾部会读到脏数据",
                tags=["对齐"],
            )
        ],
    )

    text = render_learning(learning)

    parsed = _upstream(text)
    assert len(parsed.observations) == 1
    observation = parsed.observations[0]
    assert observation.category == "pitfall"
    assert observation.content == "blockLen 非 32B 对齐时尾部会读到脏数据 #对齐"
    assert observation.tags == ["对齐"]


@pytest.mark.parametrize(
    "content",
    [
        "必须先调用 DataCopyPad(dst, src, padParams)",
        "尾块长度为 (len % 32)",
    ],
)
def test_observation_ending_in_a_paren_keeps_its_tail(content: str) -> None:
    """Upstream reads a trailing (...) as the observation's context, which would silently
    truncate any content that ends in a call signature or an expression."""
    learning = Learning(title="T", summary="S", observations=[Observation("note", content)])

    parsed = _upstream(render_learning(learning))

    assert parsed.observations[0].content == content


def test_rendered_relation_is_read_back_by_upstream() -> None:
    learning = Learning(
        title="T",
        summary="S",
        relations=[Relation(type="refines", target="DataCopy 的对齐要求")],
    )

    parsed = _upstream(render_learning(learning))

    assert len(parsed.relations) == 1
    assert parsed.relations[0].type == "refines"
    assert parsed.relations[0].target == "DataCopy 的对齐要求"


def test_a_learning_survives_a_round_trip_through_disk() -> None:
    """Revising a learning means reading it back, editing, and writing it out again."""
    learning = Learning(
        title="DataCopy 的对齐要求",
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["ascendc", "datacopy"],
        author="dyq",
        observations=[
            Observation("pitfall", "blockLen 非 32B 对齐时尾部会读到脏数据", ["对齐"]),
            Observation("verified", "改用 DataCopyPad(dst, src, padParams)"),
        ],
        relations=[Relation("refines", "UB 搬运总览")],
    )

    assert parse_learning(render_learning(learning)) == learning
