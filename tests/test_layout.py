"""Tests for the knowledge base root layout."""

import subprocess
from pathlib import Path

from knowledge_base.layout import KnowledgeBaseRoot


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
