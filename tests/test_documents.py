"""Tests for loading Markdown files into the shape the gateway indexes and displays."""

from pathlib import Path

from knowledge_base.docs.documents import Document, load_document
from knowledge_base.docs.notes import Learning, Observation, Relation, render_learning


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_learning_loads_with_its_observations_separated_from_its_prose(tmp_path: Path) -> None:
    learning = Learning(
        title="DataCopy 的对齐要求",
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["AscendC"],
        author="dyq",
        observations=[Observation("pitfall", "非对齐搬运时会读到脏数据", ["对齐"])],
        relations=[Relation("refines", "UB 搬运总览")],
    )
    write(tmp_path, "learnings/ascendc/对齐.md", render_learning(learning))

    document = load_document(tmp_path, "learnings/ascendc/对齐.md")

    assert document == Document(
        path="learnings/ascendc/对齐.md",
        title="DataCopy 的对齐要求",
        summary="非 32B 对齐的尾块会读到脏数据",
        tags=["ascendc"],
        body="# DataCopy 的对齐要求",
        observations=[Observation("pitfall", "非对齐搬运时会读到脏数据", ["对齐"])],
    )


def test_a_free_form_knowledge_file_takes_its_title_from_the_first_heading(
    tmp_path: Path,
) -> None:
    """knowledge/ is written by hand with no frontmatter required."""
    write(tmp_path, "knowledge/搬运.md", "# UB 搬运总览\n\n搬运前必须检查地址对齐。\n")

    document = load_document(tmp_path, "knowledge/搬运.md")

    assert document.title == "UB 搬运总览"
    assert document.summary == ""
    assert document.observations == []
    assert "搬运前必须检查地址对齐。" in document.body


def test_a_file_with_neither_frontmatter_nor_heading_falls_back_to_its_name(
    tmp_path: Path,
) -> None:
    write(tmp_path, "knowledge/杂记.md", "随手记的东西。\n")

    assert load_document(tmp_path, "knowledge/杂记.md").title == "杂记"


def test_tags_are_normalized_on_the_way_in(tmp_path: Path) -> None:
    write(
        tmp_path, "knowledge/a.md", "---\ntitle: T\ntags: [AscendC, Ascend_C, 对齐]\n---\n\n正文\n"
    )

    assert load_document(tmp_path, "knowledge/a.md").tags == ["ascendc", "ascend-c", "对齐"]
