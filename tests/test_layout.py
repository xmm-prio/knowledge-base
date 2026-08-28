"""Tests for the knowledge base root layout."""

import subprocess
from pathlib import Path

import pytest

from knowledge_base.layout import KnowledgeBaseRoot, OutsideDocuments, OutsideLearnings


def test_initialize_creates_the_three_content_directories(tmp_path: Path) -> None:
    root = KnowledgeBaseRoot(tmp_path)

    root.initialize()

    assert (tmp_path / "knowledge").is_dir()
    assert (tmp_path / "learnings").is_dir()
    assert (tmp_path / "codebase").is_dir()


def test_initialize_excludes_the_codebase_and_runtime_directories(tmp_path: Path) -> None:
    """basic-memory reads every file it does not exclude, and only honours the root .gitignore."""
    root = KnowledgeBaseRoot(tmp_path)

    root.initialize()

    patterns = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "codebase/" in patterns
    assert ".knowledge-base/" in patterns


def test_initialize_keeps_patterns_the_operator_added_by_hand(tmp_path: Path) -> None:
    root = KnowledgeBaseRoot(tmp_path)
    (tmp_path / ".gitignore").write_text("scratch/\n", encoding="utf-8")

    root.initialize()

    patterns = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "scratch/" in patterns
    assert "codebase/" in patterns


def test_initialize_does_not_duplicate_patterns_when_run_again(tmp_path: Path) -> None:
    root = KnowledgeBaseRoot(tmp_path)

    root.initialize()
    root.initialize()

    patterns = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert patterns.count("codebase/") == 1


def test_initialize_makes_the_root_a_git_repository(tmp_path: Path) -> None:
    """Versioning is git auto-commit, so the root has to be a repository."""
    root = KnowledgeBaseRoot(tmp_path)

    root.initialize()

    assert (tmp_path / ".git").is_dir()


def test_initialize_adopts_a_repository_the_operator_already_created(tmp_path: Path) -> None:
    root = KnowledgeBaseRoot(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ops@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "ops"], cwd=tmp_path, check=True)
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "existing.md").write_text("kept", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "existing"], cwd=tmp_path, check=True)

    root.initialize()

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert "existing" in log.stdout
    assert (tmp_path / "knowledge" / "existing.md").read_text(encoding="utf-8") == "kept"


def test_initialize_creates_the_runtime_directory(tmp_path: Path) -> None:
    """Upstream indexes are redirected here so the whole thing can be deleted and rebuilt."""
    root = KnowledgeBaseRoot(tmp_path)

    root.initialize()

    assert root.runtime_dir.is_dir()
    assert root.runtime_dir == tmp_path / ".knowledge-base"


def test_the_document_graph_keeps_its_data_under_the_runtime_directory(tmp_path: Path) -> None:
    root = KnowledgeBaseRoot(tmp_path)

    assert root.basic_memory_dir == tmp_path / ".knowledge-base" / "basic-memory"


class TestLearningPathBoundary:
    """Agents may write learnings and nothing else. This is where that is enforced -- there
    is no authentication behind it, so a path that escapes here escapes entirely."""

    def test_a_folder_and_title_become_a_file_under_learnings(self, tmp_path: Path) -> None:
        root = KnowledgeBaseRoot(tmp_path)

        path = root.resolve_learning_path("ascendc", "DataCopy 的对齐要求")

        assert path == tmp_path / "learnings" / "ascendc" / "DataCopy 的对齐要求.md"

    def test_an_empty_folder_writes_directly_under_learnings(self, tmp_path: Path) -> None:
        root = KnowledgeBaseRoot(tmp_path)

        assert root.resolve_learning_path("", "杂记") == tmp_path / "learnings" / "杂记.md"

    @pytest.mark.parametrize(
        ("folder", "title"),
        [
            ("../knowledge", "偷渡"),
            ("ascendc/../../codebase", "偷渡"),
            ("/etc", "passwd"),
            ("C:/Windows", "hosts"),
            ("ascendc", "../../knowledge/偷渡"),
            ("ascendc", "../偷渡"),
            ("", ".."),
            ("..", "偷渡"),
        ],
    )
    def test_a_path_that_leaves_learnings_is_refused(
        self, tmp_path: Path, folder: str, title: str
    ) -> None:
        root = KnowledgeBaseRoot(tmp_path)

        with pytest.raises(OutsideLearnings):
            root.resolve_learning_path(folder, title)

    def test_a_symlink_out_of_learnings_is_refused(self, tmp_path: Path) -> None:
        root = KnowledgeBaseRoot(tmp_path)
        root.initialize()
        try:
            (tmp_path / "learnings" / "escape").symlink_to(
                tmp_path / "knowledge", target_is_directory=True
            )
        except OSError:  # pragma: no cover - Windows without developer mode
            pytest.skip("creating symlinks is not permitted here")

        with pytest.raises(OutsideLearnings):
            root.resolve_learning_path("escape", "偷渡")


class TestDocumentPathBoundary:
    """People edit knowledge/ as well as learnings/, and nothing else. The service has no
    authentication, so a browser that gets past this boundary is past every boundary."""

    def test_a_document_under_knowledge_may_be_edited_by_hand(self, tmp_path: Path) -> None:
        """knowledge/ is maintained by people; only the MCP tools are kept out of it."""
        root = KnowledgeBaseRoot(tmp_path)

        path = root.resolve_document_file("knowledge/搬运 API 概览.md")

        assert path == tmp_path / "knowledge" / "搬运 API 概览.md"

    def test_a_learning_may_be_edited_by_hand_too(self, tmp_path: Path) -> None:
        root = KnowledgeBaseRoot(tmp_path)

        path = root.resolve_document_file("learnings/ascendc/对齐要求.md")

        assert path == tmp_path / "learnings" / "ascendc" / "对齐要求.md"

    @pytest.mark.parametrize(
        "relative_path",
        [
            "codebase/mops/README.md",
            ".gitignore",
            "../外面.md",
            "knowledge/../../外面.md",
            "/etc/passwd",
            "C:/Windows/hosts",
            "knowledge",
            "",
        ],
    )
    def test_a_path_outside_the_editable_directories_is_refused(
        self, tmp_path: Path, relative_path: str
    ) -> None:
        root = KnowledgeBaseRoot(tmp_path)

        with pytest.raises(OutsideDocuments):
            root.resolve_document_file(relative_path)

    def test_a_file_that_is_not_markdown_is_refused(self, tmp_path: Path) -> None:
        """The web UI edits documents. Letting it place any file at all is a different power."""
        root = KnowledgeBaseRoot(tmp_path)

        with pytest.raises(OutsideDocuments):
            root.resolve_document_file("knowledge/deploy.sh")

    def test_a_symlink_out_of_the_editable_directories_is_refused(self, tmp_path: Path) -> None:
        root = KnowledgeBaseRoot(tmp_path)
        root.initialize()
        (tmp_path / "outside").mkdir()
        try:
            (tmp_path / "knowledge" / "escape").symlink_to(
                tmp_path / "outside", target_is_directory=True
            )
        except OSError:  # pragma: no cover - Windows without developer mode
            pytest.skip("creating symlinks is not permitted here")

        with pytest.raises(OutsideDocuments):
            root.resolve_document_file("knowledge/escape/偷渡.md")
