"""Tests for reading the upstream's undocumented payloads.

The rule under test throughout: tolerant on the way in, strict on the way out. Anything that
cannot be pinned to one symbol is dropped and counted, never guessed at, because a member who
is told an answer is incomplete behaves differently from one shown a confident empty list.
"""

from knowledge_base.code.answers import read_call_chain, read_symbols


class TestReadingSymbols:
    def test_it_finds_the_list_whatever_the_payload_calls_it(self) -> None:
        for key in ("results", "matches", "symbols", "nodes"):
            found = read_symbols({key: [{"qualified_name": "x.copy.Run"}]})

            assert [one.canonical_qn for one in found.matches] == ["x.copy.Run"]

    def test_a_bare_list_is_a_list_too(self) -> None:
        found = read_symbols([{"qn": "x.copy.Run"}])

        assert [one.canonical_qn for one in found.matches] == ["x.copy.Run"]

    def test_every_match_carries_both_names(self) -> None:
        found = read_symbols([{"qualified_name": "_srv_kb_mops_src.copy.Run", "project": "mops"}])

        (one,) = found.matches
        assert one.canonical_qn == "_srv_kb_mops_src.copy.Run"
        assert one.display_qn == "mops.copy.Run"

    def test_where_a_symbol_sits_comes_along_when_the_upstream_says(self) -> None:
        found = read_symbols([{"qn": "x.Run", "file": "src/copy.c", "line": "42", "kind": "func"}])

        (one,) = found.matches
        assert (one.file, one.line, one.kind) == ("src/copy.c", 42, "func")

    def test_an_entry_without_a_name_is_counted_rather_than_invented(self) -> None:
        found = read_symbols([{"qualified_name": "x.Run"}, {"score": 0.4}])

        assert [one.canonical_qn for one in found.matches] == ["x.Run"]
        assert found.unreadable == 1

    def test_a_payload_nothing_could_be_read_from_is_kept_as_it_arrived(self) -> None:
        """A blank panel with no explanation is the one outcome worth avoiding here."""
        payload = {"unexpected": "shape"}

        found = read_symbols(payload)

        assert found.matches == []
        assert found.raw == payload

    def test_a_payload_that_did_read_does_not_drag_the_raw_along(self) -> None:
        found = read_symbols([{"qn": "x.Run"}])

        assert found.raw is None

    def test_the_repository_asked_about_names_entries_that_do_not_name_themselves(self) -> None:
        found = read_symbols([{"qn": "x.copy.Run"}], repo="mops")

        assert found.matches[0].display_qn == "mops.copy.Run"


class TestReadingCallChains:
    def test_a_chain_of_symbols_becomes_edges_between_them(self) -> None:
        payload = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Middle"}, {"qn": "c.Leaf"}]]}

        chain = read_call_chain(payload, root="a.Top", direction="outbound")

        assert [(one.caller, one.callee) for one in chain.edges] == [
            ("a.Top", "b.Middle"),
            ("b.Middle", "c.Leaf"),
        ]

    def test_edges_stated_as_edges_are_read_too(self) -> None:
        payload = {"edges": [{"caller": "a.Top", "callee": "b.Leaf"}]}

        chain = read_call_chain(payload, root="a.Top", direction="outbound")

        assert [(one.caller, one.callee) for one in chain.edges] == [("a.Top", "b.Leaf")]

    def test_a_relation_missing_an_end_is_counted_not_claimed(self) -> None:
        """A call that might be to any of three functions is worse than a call not shown."""
        payload = {"edges": [{"caller": "a.Top", "callee": "b.Leaf"}, {"caller": "a.Top"}]}

        chain = read_call_chain(payload, root="a.Top", direction="outbound")

        assert len(chain.edges) == 1
        assert chain.unresolved == 1

    def test_every_symbol_on_the_chain_becomes_a_node(self) -> None:
        payload = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Leaf"}]]}

        chain = read_call_chain(payload, root="a.Top", direction="outbound")

        assert {one.symbol.canonical_qn for one in chain.nodes} == {"a.Top", "b.Leaf"}

    def test_distance_from_the_symbol_asked_about_is_worked_out(self) -> None:
        payload = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Middle"}, {"qn": "c.Leaf"}]]}

        chain = read_call_chain(payload, root="a.Top", direction="outbound")

        assert {one.symbol.canonical_qn: one.depth for one in chain.nodes} == {
            "a.Top": 0,
            "b.Middle": 1,
            "c.Leaf": 2,
        }

    def test_tracing_callers_measures_depth_the_other_way_round(self) -> None:
        """Asked who calls `c.Leaf`, the chain grows away from the leaf, not towards it."""
        payload = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Middle"}, {"qn": "c.Leaf"}]]}

        chain = read_call_chain(payload, root="c.Leaf", direction="inbound")

        assert {one.symbol.canonical_qn: one.depth for one in chain.nodes} == {
            "c.Leaf": 0,
            "b.Middle": 1,
            "a.Top": 2,
        }

    def test_nodes_carry_the_short_name_and_the_one_to_ask_with(self) -> None:
        payload = {"edges": [{"caller": "_srv_kb_mops_src.copy.Run", "callee": "x.Leaf"}]}

        chain = read_call_chain(payload, root="x.Leaf", direction="inbound", repo="mops")

        by_name = {one.symbol.canonical_qn: one.symbol.display_qn for one in chain.nodes}
        assert by_name["_srv_kb_mops_src.copy.Run"] == "mops.copy.Run"

    def test_a_chain_nothing_could_be_read_from_keeps_what_arrived(self) -> None:
        chain = read_call_chain({"unexpected": "shape"}, root="a.Top", direction="inbound")

        assert chain.edges == []
        assert chain.raw == {"unexpected": "shape"}

    def test_what_was_asked_travels_with_the_answer(self) -> None:
        chain = read_call_chain({}, root="a.Top", direction="inbound")

        assert (chain.root, chain.direction) == ("a.Top", "inbound")
