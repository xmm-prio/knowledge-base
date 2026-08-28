"""The on-disk layout of a knowledge base root."""

from pathlib import Path

from knowledge_base.vcs import Repository

CONTENT_DIRECTORIES = ("knowledge", "learnings", "codebase")

RUNTIME_DIRECTORY = ".knowledge-base"

# basic-memory only reads the root .gitignore, and understands nothing beyond plain
# directory-name patterns -- no negation, no ** semantics. Keep these patterns naive.
IGNORED_PATTERNS = ("codebase/", f"{RUNTIME_DIRECTORY}/")


class KnowledgeBaseRoot:
    """A directory that holds one knowledge base."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def knowledge_dir(self) -> Path:
        return self.path / "knowledge"

    @property
    def learnings_dir(self) -> Path:
        return self.path / "learnings"

    @property
    def codebase_dir(self) -> Path:
        return self.path / "codebase"

    @property
    def runtime_dir(self) -> Path:
        """Upstream indexes live here; deleting it costs nothing but a reindex."""
        return self.path / RUNTIME_DIRECTORY

    def initialize(self) -> None:
        """Create the layout. Safe to run against an already-initialized root."""
        for name in CONTENT_DIRECTORIES:
            (self.path / name).mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_ignored()
        Repository(self.path).ensure()

    def _ensure_ignored(self) -> None:
        gitignore = self.path / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
        missing = [p for p in IGNORED_PATTERNS if p not in existing]
        if not missing:
            return
        gitignore.write_text("\n".join(existing + missing) + "\n", encoding="utf-8")
