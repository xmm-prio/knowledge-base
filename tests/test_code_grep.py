"""Tests for reading `search_code`, the one read tool that answers in prose.

It takes no `format` argument, so there is no JSON to ask for: the report below is the whole
contract. Two sections matter and they answer different questions -- the declarations the
matches fall inside, which is what makes a hit clickable, and the matching lines themselves,
which is the only thing that finds a comment or a language the upstream never parsed.
"""

from tests.upstream_replies import GREP

from knowledge_base.code.grep import read_text_matches


def from_one(report: object, repo: str | None = "ops-nn"):
    return read_text_matches([(repo, report)])


class TestReadingTheDeclarationsAroundAMatch:
    def test_each_result_row_becomes_a_symbol_worth_clicking(self) -> None:
        found = from_one(GREP)

        assert [one.canonical_qn.rsplit(".", 1)[-1] for one in found.symbols] == [
            "aclnnConvolutionGetWorkspaceSize",
            "GenTiling",
        ]

    def test_the_columns_after_the_path_are_read_from_the_right(self) -> None:
        """A path could contain a space, so the middle is whatever the ends leave over."""
        found = from_one(GREP)

        assert found.symbols[0].file == (
            "conv/convolution_forward/op_host/op_api/aclnn_convolution.cpp"
        )
        assert found.symbols[0].line == 5384
        assert found.symbols[0].kind == "Function"

    def test_symbols_carry_a_short_name_like_every_other_search_does(self) -> None:
        found = from_one(GREP)

        assert found.symbols[0].display_qn.startswith("ops-nn.")


class TestReadingTheMatchingLines:
    def test_every_raw_row_is_a_file_a_line_and_what_is_on_it(self) -> None:
        found = from_one(GREP)

        assert len(found.lines) == 3
        assert found.lines[0].line == 24

    def test_a_quoted_line_is_unquoted_and_an_unquoted_one_is_left_alone(self) -> None:
        found = from_one(GREP)

        assert found.lines[0].text.startswith("constexpr MatmulConfig")
        assert found.lines[1].text == "BEGIN_TILING_DATA_DEF(FusedMatmulGeluTilingData)"

    def test_content_with_spaces_survives_being_split_into_columns(self) -> None:
        found = from_one(GREP)

        assert found.lines[2].text == " * @brief aclnnFusedMatmulGelu first-stage API."


class TestSayingHowMuchWasLeftOut:
    def test_the_upstreams_own_count_of_matches_is_carried(self) -> None:
        found = from_one(GREP)

        assert found.total == 500

    def test_handing_back_three_of_five_hundred_is_reported_as_truncated(self) -> None:
        found = from_one(GREP)

        assert found.truncated is True


class TestSeveralRepositoriesAtOnce:
    def test_counts_add_up_across_repositories(self) -> None:
        found = read_text_matches([("ge", GREP), ("ops-nn", GREP)])

        assert found.total == 1000
        assert len(found.symbols) == 4

    def test_a_name_two_repositories_share_is_told_apart(self) -> None:
        found = read_text_matches([("ge", GREP), ("ops-nn", GREP)])

        assert len({one.display_qn for one in found.symbols}) == 4


class TestWhenTheReportIsNotOne:
    def test_something_unreadable_is_kept_rather_than_shown_as_nothing_found(self) -> None:
        found = from_one("who knows what this is")

        assert found.symbols == []
        assert found.raw == ["who knows what this is"]

    def test_a_report_that_did_read_does_not_drag_the_raw_along(self) -> None:
        assert from_one(GREP).raw is None
