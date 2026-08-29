"""Tests for how the gateway names repositories and symbols.

Two things are being pinned here. A repository has one identity no matter how the upstream
spells the path it was handed, and a symbol has two names on purpose -- one to read, one to
ask with -- which must never be confused for each other.
"""

from knowledge_base.code.naming import display_name, readable_names, repo_key, short_id


class TestRepoKey:
    def test_the_same_repository_under_three_spellings_is_one_repository(self) -> None:
        """The upstream reports whatever path it was given; the directory is the identity."""
        spellings = ["mops", "/srv/kb/codebase/mops", "C:\\kb\\codebase\\Mops"]

        assert len({repo_key(one) for one in spellings}) == 1

    def test_a_trailing_separator_does_not_make_a_different_repository(self) -> None:
        assert repo_key("/srv/kb/codebase/mops/") == repo_key("mops")

    def test_two_different_directories_stay_different(self) -> None:
        assert repo_key("codebase/mops") != repo_key("codebase/ascendc-samples")


class TestDisplayName:
    def test_a_name_is_shown_under_its_repository(self) -> None:
        assert display_name("DataCopyPad", "mops") == "mops.DataCopyPad"

    def test_the_machine_that_indexed_it_is_not_worth_screen_space(self) -> None:
        """The front of a qualified name is a flattened absolute path, and it is not stable."""
        canonical = "_srv_kb_codebase_mops_src.copy.DataCopyPad"

        assert display_name(canonical, "mops") == "mops.copy.DataCopyPad"

    def test_a_windows_drive_is_dropped_the_same_way(self) -> None:
        canonical = "C__Users_kb_codebase_mops_src.copy.DataCopyPad"

        assert display_name(canonical, "mops") == "mops.copy.DataCopyPad"

    def test_a_name_that_is_nothing_but_path_still_gets_called_something(self) -> None:
        assert display_name("_srv_kb_codebase_mops_src", "mops") == "mops._srv_kb_codebase_mops_src"

    def test_without_a_repository_the_tail_stands_alone(self) -> None:
        assert display_name("a.b.copy.DataCopyPad", "") == "copy.DataCopyPad"


class TestDisambiguation:
    def test_names_that_do_not_collide_stay_short(self) -> None:
        names = readable_names([("x.copy.Run", "mops"), ("x.move.Run", "mops")])

        assert set(names.values()) == {"mops.copy.Run", "mops.move.Run"}

    def test_two_symbols_that_would_read_alike_are_told_apart(self) -> None:
        """Clicking the wrong one of two identical rows is a mistake nobody notices making."""
        names = readable_names([("a_src.copy.Run", "mops"), ("b_src.copy.Run", "mops")])

        assert len(set(names.values())) == 2
        assert all(one.startswith("mops.copy.Run#") for one in names.values())

    def test_the_short_identifier_is_the_same_one_next_time(self) -> None:
        assert short_id("a_src.copy.Run") == short_id("a_src.copy.Run")

    def test_a_collision_does_not_lengthen_the_names_around_it(self) -> None:
        names = readable_names(
            [("a_src.copy.Run", "mops"), ("b_src.copy.Run", "mops"), ("x.move.Go", "mops")]
        )

        assert names[("x.move.Go", "mops")] == "mops.move.Go"

    def test_one_name_in_two_repositories_is_two_symbols(self) -> None:
        """Vendored code gives two repositories the same qualified name for different files."""
        names = readable_names([("copy.Run", "ge"), ("copy.Run", "ops-nn")])

        assert len(set(names.values())) == 2
