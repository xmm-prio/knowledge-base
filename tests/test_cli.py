"""Tests for the command line, from the operator's side of it."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from knowledge_base.cli import app

runner = CliRunner()

LEARNING = """\
---
title: 对齐要求
summary: DataCopy 的搬运长度必须按 32 字节对齐
tags: [ascendc]
---

## Observations
- [pitfall] 未对齐的搬运长度会让上游静默截断 #ascendc
"""


def place(root: Path, relative: str, text: str = LEARNING) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestInit:
    def test_it_lays_out_a_new_knowledge_base(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "--root", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "knowledge").is_dir()
        assert (tmp_path / "learnings").is_dir()
        assert (tmp_path / "codebase").is_dir()
        assert (tmp_path / ".git").is_dir()

    def test_it_leaves_an_existing_knowledge_base_alone(self, tmp_path: Path) -> None:
        place(tmp_path, "learnings/对齐要求.md")

        result = runner.invoke(app, ["init", "--root", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "learnings/对齐要求.md").read_text(encoding="utf-8") == LEARNING

    def test_the_indexes_are_kept_out_of_history(self, tmp_path: Path) -> None:
        """codebase/ has its own git and .knowledge-base/ is rebuildable. See ADR-0003."""
        runner.invoke(app, ["init", "--root", str(tmp_path)])

        ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert ignored == ["codebase/", ".knowledge-base/"]


class TestReindexDocuments:
    def test_it_reports_how_much_it_indexed(self, tmp_path: Path) -> None:
        place(tmp_path, "learnings/ascendc/对齐要求.md")
        place(tmp_path, "knowledge/上手/环境.md")

        result = runner.invoke(app, ["reindex", "documents", "--root", str(tmp_path)])

        assert result.exit_code == 0
        assert "已索引 2 篇文档" in result.stdout


class TestReindexCode:
    def test_it_says_so_when_there_is_nothing_to_index(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["reindex", "code", "--root", str(tmp_path)])

        assert result.exit_code == 0
        assert "codebase/ 下没有代码库" in result.stdout

    def test_it_leaves_the_document_graph_alone(self, tmp_path: Path) -> None:
        """Indexing code has no reason to pay for the document upstream's migrations, and its
        directory appearing is the only evidence that it was started at all."""
        place(tmp_path, "learnings/ascendc/对齐要求.md")

        runner.invoke(app, ["reindex", "code", "--root", str(tmp_path)])

        assert not (tmp_path / ".knowledge-base" / "basic-memory").exists()


class TestStatus:
    def test_it_reports_the_size_of_the_knowledge_base(self, tmp_path: Path) -> None:
        place(tmp_path, "learnings/ascendc/对齐要求.md")

        result = runner.invoke(app, ["status", "--root", str(tmp_path)])

        assert result.exit_code == 0
        assert "文档：1 篇，观察 1 条" in result.stdout

    def test_it_says_the_code_domain_is_down_when_the_binary_is_absent(
        self, tmp_path: Path
    ) -> None:
        """A Windows workstation has no build of it, and the command still has to work."""
        result = runner.invoke(app, ["status", "--root", str(tmp_path)])

        assert "代码域上游：不可用" in result.stdout

    def test_it_prints_a_snippet_a_colleague_can_paste(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["status", "--root", str(tmp_path), "--host", "kb.internal", "--port", "9000"]
        )

        assert '"url": "http://kb.internal:9000/mcp"' in result.stdout
        assert '"type": "remote"' in result.stdout


class TestTheCommandSet:
    def test_the_operator_is_told_what_the_commands_are(self) -> None:
        result = runner.invoke(app, ["--help"])

        for command in ("init", "server", "reindex", "status"):
            assert command in result.stdout
