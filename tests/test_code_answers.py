"""Tests for reading the upstream's payloads, against payloads it really sent.

The rule under test throughout: tolerant on the way in, strict on the way out. Anything that
cannot be pinned to one symbol is dropped and counted, never guessed at, because a member who
is told an answer is incomplete behaves differently from one shown a confident empty list.

Most cases here run on `upstream_replies`, captured verbatim from the installed binary. The
readers were once written against payloads we had imagined instead, and every one of those
tests passed while the gateway could not read a single real result.
"""

from typing import Any

from tests.upstream_replies import (
    AMATMULB,
    NO_CALLERS,
    NOTHING_MATCHED,
    SEARCH_BY_KEYWORD,
    SEARCH_BY_NAME,
    SNIPPET,
    TRACED,
)

from knowledge_base.code.answers import (
    SymbolMatches,
    read_call_chain,
    read_source,
    read_symbols,
)


def from_one(payload: Any, repo: str | None = None) -> SymbolMatches:
    """One repository's answer, read the way the engine reads a search that named one."""
    return read_symbols([(repo, payload)])


class TestReadingTheShapeTheUpstreamActuallyAnswersIn:
    """`search_graph` answers in a table, and in two different tables at that."""

    def test_a_grouped_row_is_only_a_name_once_its_group_is_put_back_on(self) -> None:
        """The row says `AMatMulB`; asking the upstream that finds nothing."""
        found = from_one(SEARCH_BY_NAME)

        assert found.matches[0].canonical_qn == AMATMULB

    def test_the_group_says_which_file_its_rows_live_in(self) -> None:
        found = from_one(SEARCH_BY_NAME)

        assert found.matches[0].file == (
            "matmul/mat_mul_v3/op_kernel/mat_mul_sc_splitk_kernel_gm_to_l1.h"
        )

    def test_a_span_of_lines_is_read_as_where_it_starts(self) -> None:
        found = from_one(SEARCH_BY_NAME)

        assert found.matches[0].line == 725

    def test_what_the_upstream_calls_a_label_is_what_a_symbol_is(self) -> None:
        found = from_one(SEARCH_BY_NAME)

        assert [one.kind for one in found.matches] == ["Function", "Macro"]

    def test_a_ranked_search_answers_in_flat_rows_with_whole_names(self) -> None:
        """The same tool, a different shape, and both have to read."""
        found = from_one(SEARCH_BY_KEYWORD)

        assert len(found.matches) == 2
        assert found.matches[0].canonical_qn.endswith(".quant_batch_matmul_v3")
        assert found.matches[0].line == 212

    def test_how_many_matched_is_carried_even_when_few_came_back(self) -> None:
        found = from_one(SEARCH_BY_NAME)

        assert (found.total, found.truncated) == (5844, True)

    def test_nothing_matching_is_an_empty_answer_and_not_an_unreadable_one(self) -> None:
        found = from_one(NOTHING_MATCHED)

        assert (found.matches, found.unreadable, found.total) == ([], 0, 0)

    def test_an_empty_answer_is_not_dressed_up_as_a_broken_one(self) -> None:
        """`raw` is what makes the page show a payload dump. Nothing matched is not that."""
        found = from_one(NOTHING_MATCHED)

        assert found.raw is None


class TestReadingSymbols:
    def test_every_match_carries_both_names(self) -> None:
        found = from_one({"cols": ["qn"], "rows": [["_srv_kb_mops_src.copy.Run"]]}, repo="mops")

        (one,) = found.matches
        assert one.canonical_qn == "_srv_kb_mops_src.copy.Run"
        assert one.display_qn == "mops.copy.Run"

    def test_an_entry_without_a_name_is_counted_rather_than_invented(self) -> None:
        found = from_one({"cols": ["qn", "label"], "rows": [["x.Run", "Function"], [None, "F"]]})

        assert [one.canonical_qn for one in found.matches] == ["x.Run"]
        assert found.unreadable == 1

    def test_a_payload_nothing_could_be_read_from_is_kept_as_it_arrived(self) -> None:
        """A blank panel with no explanation is the one outcome worth avoiding here."""
        payload = {"unexpected": "shape"}

        found = from_one(payload)

        assert found.matches == []
        assert found.raw == [payload]

    def test_a_payload_that_did_read_does_not_drag_the_raw_along(self) -> None:
        found = from_one(SEARCH_BY_NAME)

        assert found.raw is None

    def test_a_plainer_shape_would_still_read(self) -> None:
        """The table is not in any contract we were handed, so a version that answers in
        plain objects should degrade to a readable list rather than an empty one."""
        for key in ("results", "matches", "symbols", "nodes"):
            found = from_one({key: [{"qualified_name": "x.copy.Run"}]})

            assert [one.canonical_qn for one in found.matches] == ["x.copy.Run"]


class TestReadingSeveralRepositoriesAtOnce:
    """A search that named no repository is one answer per repository, read as one."""

    def test_the_repositories_stay_in_the_order_they_were_asked(self) -> None:
        found = read_symbols(
            [("ge", {"cols": ["qn"], "rows": [["a.Run"]]})]
            + [("ops-nn", {"cols": ["qn"], "rows": [["b.Run"]]})],
        )

        assert [one.repo for one in found.matches] == ["ge", "ops-nn"]

    def test_a_name_two_repositories_share_is_told_apart(self) -> None:
        """Disambiguating within a repository and then merging would let one name repeat."""
        page = {"cols": ["qn"], "rows": [["copy.Run"]]}

        found = read_symbols([("ge", page), ("ops-nn", page)])

        assert len({one.display_qn for one in found.matches}) == 2

    def test_what_each_repository_could_not_read_is_summed(self) -> None:
        blank = {"cols": ["qn"], "rows": [[None]]}
        found = read_symbols([("ge", blank), ("ops-nn", {"cols": ["qn"], "rows": [["b"], [None]]})])

        assert found.unreadable == 2

    def test_the_totals_add_up_and_truncation_anywhere_counts(self) -> None:
        found = read_symbols(
            [
                ("ge", {"cols": ["qn"], "rows": [["a.Run"]], "total": 9, "has_more": True}),
                ("ops-nn", {"cols": ["qn"], "rows": [["b.Run"]], "total": 2}),
            ]
        )

        assert (found.total, found.truncated) == (11, True)

    def test_a_repository_that_did_not_say_how_many_leaves_the_total_unstated(self) -> None:
        """A partial sum presented as a whole one is worse than admitting we do not know."""
        found = read_symbols(
            [
                ("ge", {"cols": ["qn"], "rows": [["a.Run"]], "total": 9}),
                ("ops-nn", {"cols": ["qn"], "rows": [["b.Run"]]}),
            ]
        )

        assert found.total is None


class TestReadingCallChains:
    """What the upstream reports is a distance and an evidence class, never an edge."""

    def test_each_hop_becomes_a_node_under_the_name_to_ask_with(self) -> None:
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        assert [one.symbol.canonical_qn.rsplit(".", 1)[-1] for one in chain.nodes] == [
            "Compute",
            "Process",
        ]

    def test_how_far_away_each_hop_is_comes_straight_from_the_upstream(self) -> None:
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        assert [one.depth for one in chain.nodes] == [1, 2]

    def test_how_a_hop_was_resolved_travels_with_it(self) -> None:
        """Whether an edge is worth believing is the reader's call, so give them the grounds."""
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        assert (chain.nodes[0].strategy, chain.nodes[0].confidence) == ("lsp", 0.98)

    def test_a_hop_the_upstream_could_not_resolve_is_counted_not_shown(self) -> None:
        """A call that might be to any of three functions is worse than a call not shown."""
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        shown = {one.symbol.canonical_qn.rsplit(".", 1)[-1] for one in chain.nodes}
        assert "MaybeCompute" not in shown
        assert chain.unresolved == 1

    def test_only_the_first_hop_becomes_an_edge(self) -> None:
        """Two hops away says how far, never through what. The second edge would be invented."""
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        (edge,) = chain.edges
        assert edge.caller.endswith(".Compute")
        assert edge.callee == AMATMULB

    def test_tracing_outward_turns_the_edges_round(self) -> None:
        outward = {"callees": TRACED["callers"], "callees_total": 3}

        chain = read_call_chain(outward, root=AMATMULB, direction="outbound")

        (edge,) = chain.edges
        assert edge.caller == AMATMULB

    def test_nodes_carry_the_short_name_and_the_one_to_ask_with(self) -> None:
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound", repo="ops-nn")

        assert chain.nodes[0].symbol.display_qn.startswith("ops-nn.")

    def test_how_many_callers_there_are_is_the_upstreams_own_count(self) -> None:
        chain = read_call_chain(TRACED, root=AMATMULB, direction="inbound")

        assert chain.total == 3

    def test_nothing_calling_it_is_an_answer_and_not_a_failure(self) -> None:
        chain = read_call_chain(NO_CALLERS, root=AMATMULB, direction="inbound")

        assert (chain.nodes, chain.edges, chain.unresolved) == ([], [], 0)

    def test_a_chain_nothing_could_be_read_from_keeps_what_arrived(self) -> None:
        chain = read_call_chain({"unexpected": "shape"}, root="a.Top", direction="inbound")

        assert chain.edges == []
        assert chain.raw == {"unexpected": "shape"}

    def test_what_was_asked_travels_with_the_answer(self) -> None:
        chain = read_call_chain({}, root="a.Top", direction="inbound")

        assert (chain.root, chain.direction) == ("a.Top", "inbound")


class TestReadingSource:
    def test_the_body_and_where_it_came_from_are_read(self) -> None:
        source = read_source(SNIPPET, qualified_name=AMATMULB)

        assert source is not None
        assert source.text.startswith("/**")
        assert source.start_line == 1

    def test_the_path_shown_is_the_one_inside_the_repository(self) -> None:
        """The absolute path is the deployment host's, which means nothing to a reader."""
        source = read_source(SNIPPET, qualified_name=AMATMULB)

        assert source is not None
        assert source.file == "matmul/mat_mul_v3/op_kernel/mat_mul_sc_splitk_kernel_gm_to_l1.h"

    def test_a_body_the_upstream_cut_short_says_so(self) -> None:
        """Read as whole, a clipped body is how somebody concludes a function does not handle
        a case it handles on line 600."""
        source = read_source(SNIPPET, qualified_name=AMATMULB)

        assert source is not None
        assert source.clipped_at == 500

    def test_something_that_is_not_a_snippet_is_not_read_as_one(self) -> None:
        assert read_source({"error": "nope"}, qualified_name=AMATMULB) is None
