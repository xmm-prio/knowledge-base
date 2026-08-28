"""Tests for tag normalization.

Tags are free-form, so the server is the only thing standing between the tag cloud and
five spellings of the same concept.
"""

import pytest

from knowledge_base.docs.tags import normalize_tag, normalize_tags


@pytest.mark.parametrize(
    ("written", "normalized"),
    [
        ("AscendC", "ascendc"),
        ("Ascend C", "ascend-c"),
        ("ascend_c", "ascend-c"),
        ("  ascend--c  ", "ascend-c"),
        ("#ascendc", "ascendc"),
        ("对齐", "对齐"),
        ("UB 搬运", "ub-搬运"),
    ],
)
def test_spellings_of_one_concept_collapse_to_one_tag(written: str, normalized: str) -> None:
    assert normalize_tag(written) == normalized


def test_normalizing_a_list_drops_duplicates_and_keeps_the_written_order() -> None:
    assert normalize_tags(["AscendC", "对齐", "Ascend_C", "ascendc"]) == [
        "ascendc",
        "对齐",
        "ascend-c",
    ]


def test_a_tag_that_normalizes_to_nothing_is_dropped() -> None:
    assert normalize_tags(["", "  ", "-", "对齐"]) == ["对齐"]
