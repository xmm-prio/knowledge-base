"""Tests for joining a directory on disk to the project the upstream calls it.

The bug this module exists for: a repository indexed and answerable was shown as not indexed,
and every question about it was refused, because both sides were compared by name and the
upstream does not keep the name. Everything here is about the join being made on the path.
"""

from pathlib import Path

import pytest

from knowledge_base.code.projects import PAGE, Catalog
from knowledge_base.code.upstream import UpstreamUnavailable


class Listing:
    """An upstream that reports the projects it was built with, a page at a time."""

    def __init__(self, *projects: dict[str, object], failing: Exception | None = None) -> None:
        self.projects = list(projects)
        self.failing = failing
        self.pages: list[dict[str, object]] = []

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        if self.failing is not None:
            raise self.failing
        self.pages.append(dict(arguments))
        offset = int(str(arguments.get("offset", 0)))
        limit = int(str(arguments.get("limit", PAGE)))
        shown = self.projects[offset : offset + limit]
        return {
            "projects": shown,
            "total": len(self.projects),
            "offset": offset,
            "returned": len(shown),
            "has_more": offset + len(shown) < len(self.projects),
        }


def indexed(root: Path, name: str) -> dict[str, object]:
    """One entry as the upstream writes it: a derived name, and the path it came from."""
    return {"name": f"flattened-{name}", "root_path": str(root / name)}


class TestFindingARepository:
    def test_a_directory_is_found_under_the_name_the_upstream_derived(self, tmp_path: Path) -> None:
        catalog = Catalog.read_from(Listing(indexed(tmp_path, "ops-nn")))

        found = catalog.of(tmp_path / "ops-nn")

        assert found is not None
        assert found.name == "flattened-ops-nn"

    def test_a_directory_the_upstream_never_indexed_is_absent(self, tmp_path: Path) -> None:
        catalog = Catalog.read_from(Listing(indexed(tmp_path, "ops-nn")))

        assert catalog.of(tmp_path / "ge") is None

    def test_a_trailing_separator_is_the_same_directory(self, tmp_path: Path) -> None:
        """The upstream reports the path it was handed, and it was handed whatever it was."""
        listed: dict[str, object] = {"name": "flattened", "root_path": f"{tmp_path / 'ge'}/"}

        catalog = Catalog.read_from(Listing(listed))

        assert catalog.of(tmp_path / "ge") is not None

    def test_a_project_without_a_root_is_not_one_we_can_place(self, tmp_path: Path) -> None:
        """Without a path there is nothing to match on, and guessing the name is the bug."""
        catalog = Catalog.read_from(Listing({"name": "flattened-ge"}, indexed(tmp_path, "ops-nn")))

        assert len(catalog) == 1


class TestReadingTheWholeListing:
    def test_it_pages_until_the_upstream_says_there_is_no_more(self, tmp_path: Path) -> None:
        """Stopping at the first page silently hides every repository past the limit."""
        upstream = Listing(*(indexed(tmp_path, f"repo-{n}") for n in range(PAGE + 5)))

        catalog = Catalog.read_from(upstream)

        assert len(catalog) == PAGE + 5
        assert [page["offset"] for page in upstream.pages] == [0, PAGE]

    def test_the_last_repository_of_the_last_page_is_still_found(self, tmp_path: Path) -> None:
        upstream = Listing(*(indexed(tmp_path, f"repo-{n}") for n in range(PAGE + 1)))

        catalog = Catalog.read_from(upstream)

        assert catalog.of(tmp_path / f"repo-{PAGE}") is not None


class TestWhenTheUpstreamCannotSay:
    def test_asking_it_to_be_read_fails_loudly(self, tmp_path: Path) -> None:
        """An absent binary and an unindexed repository must not arrive at the same answer."""
        upstream = Listing(failing=UpstreamUnavailable("the binary is gone"))

        with pytest.raises(UpstreamUnavailable):
            Catalog.read_from(upstream)

    def test_a_best_effort_reading_is_empty_instead(self, tmp_path: Path) -> None:
        """Listing what is on disk must survive an upstream that cannot be reached."""
        upstream = Listing(failing=UpstreamUnavailable("the binary is gone"))

        catalog = Catalog.best_effort(upstream)

        assert len(catalog) == 0
