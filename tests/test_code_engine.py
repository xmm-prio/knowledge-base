"""Tests for the code domain facade.

This is the seam the MCP tools and the REST API both sit on: every question about indexed
source code goes through here, and the upstream binary is never visible past it.
"""

import re
from pathlib import Path

import pytest

from knowledge_base.code.answers import CallChain, SymbolMatches
from knowledge_base.code.engine import CodeEngine, Direction, SearchMode, UnknownRepo
from knowledge_base.code.failures import InvalidQuery
from knowledge_base.layout import KnowledgeBaseRoot


class FakeUpstream:
    """Stands in for the supervised binary, answering with canned payloads."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.failing: set[str] = set()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool, arguments))
        if tool in self.failing:
            raise RuntimeError(f"{tool} refused")
        return self.answers.get(tool, {})

    def arguments_for(self, tool: str) -> list[dict[str, object]]:
        return [arguments for name, arguments in self.calls if name == tool]


@pytest.fixture
def root(tmp_path: Path) -> KnowledgeBaseRoot:
    base = KnowledgeBaseRoot(tmp_path)
    base.initialize()
    return base


def place_repo(root: KnowledgeBaseRoot, name: str) -> None:
    (root.codebase_dir / name / "src").mkdir(parents=True)
    (root.codebase_dir / name / "src" / "main.c").write_text("int main(void){return 0;}\n")


class TestListRepos:
    def test_it_lists_every_directory_operators_placed_under_codebase(
        self, root: KnowledgeBaseRoot
    ) -> None:
        place_repo(root, "mops")
        place_repo(root, "ascendc-samples")

        engine = CodeEngine(root, FakeUpstream())

        assert [repo.name for repo in engine.list_repos()] == ["ascendc-samples", "mops"]

    def test_it_reports_where_each_repo_lives_relative_to_the_root(
        self, root: KnowledgeBaseRoot
    ) -> None:
        place_repo(root, "mops")

        engine = CodeEngine(root, FakeUpstream())

        assert [repo.path for repo in engine.list_repos()] == ["codebase/mops"]

    def test_it_ignores_loose_files_and_hidden_directories(self, root: KnowledgeBaseRoot) -> None:
        """codebase/ is populated by hand, so it collects strays that are not repos."""
        place_repo(root, "mops")
        (root.codebase_dir / "notes.txt").write_text("scratch")
        (root.codebase_dir / ".cache").mkdir()

        engine = CodeEngine(root, FakeUpstream())

        assert [repo.name for repo in engine.list_repos()] == ["mops"]

    def test_a_repo_the_upstream_has_indexed_is_marked_indexed(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """Being on disk and being searchable are different states, and callers need both."""
        place_repo(root, "mops")
        place_repo(root, "fresh")
        upstream = FakeUpstream({"list_projects": {"projects": [{"name": "mops"}]}})

        engine = CodeEngine(root, upstream)

        assert {repo.name: repo.indexed for repo in engine.list_repos()} == {
            "mops": True,
            "fresh": False,
        }

    def test_the_upstream_naming_a_repo_by_path_is_the_same_repo(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """The upstream reports back whatever path it was handed, and it was handed absolutes."""
        place_repo(root, "mops")
        listing = {"projects": [{"name": str(root.codebase_dir / "mops")}]}

        engine = CodeEngine(root, FakeUpstream({"list_projects": listing}))

        assert [repo.indexed for repo in engine.list_repos()] == [True]

    def test_a_repo_the_upstream_lists_but_cannot_search_is_not_indexed(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """Listed means it remembers indexing it. Indexed, on screen, has to mean answerable."""
        place_repo(root, "mops")
        upstream = FakeUpstream({"list_projects": {"projects": [{"name": "mops"}]}})
        upstream.failing.add("search_graph")

        engine = CodeEngine(root, upstream)

        assert [repo.indexed for repo in engine.list_repos()] == [False]

    def test_a_repo_the_upstream_never_heard_of_costs_no_probe(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """A knowledge base of unindexed sources must not pay a round trip per directory."""
        place_repo(root, "fresh")
        upstream = FakeUpstream({"list_projects": {"projects": []}})

        CodeEngine(root, upstream).list_repos()

        assert upstream.arguments_for("search_graph") == []

    def test_it_survives_an_upstream_that_cannot_answer(self, root: KnowledgeBaseRoot) -> None:
        """A dead binary must not hide the repos an operator can see in the filesystem."""

        class Broken:
            def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
                raise RuntimeError("binary is not running")

        place_repo(root, "mops")

        engine = CodeEngine(root, Broken())

        assert [(repo.name, repo.indexed) for repo in engine.list_repos()] == [("mops", False)]


class TestIndexing:
    def test_rebuilding_everything_hands_the_upstream_an_absolute_path_per_repo(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """The upstream resolves relative paths against its own working directory, not ours."""
        place_repo(root, "mops")
        place_repo(root, "ascendc-samples")
        upstream = FakeUpstream()

        list(CodeEngine(root, upstream).rebuild_all())

        assert upstream.arguments_for("index_repository") == [
            {"repo_path": str(root.codebase_dir / "ascendc-samples")},
            {"repo_path": str(root.codebase_dir / "mops")},
        ]

    def test_rebuilding_everything_reports_one_outcome_per_repo(
        self, root: KnowledgeBaseRoot
    ) -> None:
        place_repo(root, "mops")
        place_repo(root, "ascendc-samples")

        outcomes = list(CodeEngine(root, FakeUpstream()).rebuild_all())

        assert [(o.repo, o.ok) for o in outcomes] == [("ascendc-samples", True), ("mops", True)]

    def test_one_repo_the_upstream_chokes_on_does_not_stop_the_others(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """Startup indexes everything; one unparseable repo must not leave the rest unsearchable."""
        place_repo(root, "mops")
        place_repo(root, "ascendc-samples")
        upstream = FakeUpstream()
        upstream.failing.add("index_repository")

        outcomes = list(CodeEngine(root, upstream).rebuild_all())

        assert [o.ok for o in outcomes] == [False, False]
        assert len(upstream.arguments_for("index_repository")) == 2

    def test_rebuilding_one_repo_returns_what_the_upstream_said_about_it(
        self, root: KnowledgeBaseRoot
    ) -> None:
        """The upstream flags a partially persisted index as degraded, and callers must see it."""
        place_repo(root, "mops")
        upstream = FakeUpstream({"index_repository": {"status": "degraded", "nodes": 12}})

        outcome = CodeEngine(root, upstream).rebuild("mops")

        assert outcome.ok is True
        assert outcome.payload == {"status": "degraded", "nodes": 12}

    def test_it_refuses_a_repo_that_is_not_under_codebase(self, root: KnowledgeBaseRoot) -> None:
        """Nothing else stops a caller from steering the upstream at an arbitrary directory."""
        with pytest.raises(UnknownRepo):
            CodeEngine(root, FakeUpstream()).rebuild("../../etc")


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def engine(root: KnowledgeBaseRoot, upstream: FakeUpstream) -> CodeEngine:
    place_repo(root, "mops")
    return CodeEngine(root, upstream)


class TestAsking:
    def test_the_architecture_overview_is_scoped_to_one_repo(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.get_architecture("mops")

        assert upstream.arguments_for("get_architecture") == [{"project": "mops"}]

    def test_asking_about_an_unknown_repo_is_refused(self, engine: CodeEngine) -> None:
        with pytest.raises(UnknownRepo):
            engine.get_architecture("nope")

    def test_symbol_search_goes_to_the_graph_and_text_search_greps(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        """The two modes are different upstream tools, which is exactly why we hide them."""
        engine.search_code("DataCopyPad", mode=SearchMode.SYMBOL, repo="mops")
        engine.search_code("DataCopyPad", mode=SearchMode.TEXT, repo="mops")

        assert upstream.arguments_for("search_graph") == [
            {"name_pattern": "DataCopyPad", "project": "mops"}
        ]
        assert upstream.arguments_for("search_code") == [
            {"query": "DataCopyPad", "project": "mops"}
        ]

    def test_a_search_without_a_repo_spans_every_indexed_one(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.search_code("DataCopyPad")

        assert upstream.arguments_for("search_graph") == [{"name_pattern": "DataCopyPad"}]

    def test_reading_a_symbol_asks_for_it_by_qualified_name(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.read_symbol("src.copy.DataCopyPad")

        assert upstream.arguments_for("get_code_snippet") == [
            {"qualified_name": "src.copy.DataCopyPad"}
        ]

    def test_tracing_callers_is_the_default_direction(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        """ "Who calls this" is the question people actually arrive with."""
        engine.trace_calls("DataCopyPad")

        assert upstream.arguments_for("trace_path") == [
            {"function_name": "DataCopyPad", "direction": Direction.INBOUND, "depth": 3}
        ]

    def test_tracing_accepts_a_direction_and_a_depth(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.trace_calls("DataCopyPad", direction=Direction.OUTBOUND, depth=5, repo="mops")

        assert upstream.arguments_for("trace_path") == [
            {
                "function_name": "DataCopyPad",
                "direction": Direction.OUTBOUND,
                "depth": 5,
                "project": "mops",
            }
        ]

    def test_a_depth_the_upstream_cannot_honour_is_refused_here(self, engine: CodeEngine) -> None:
        """Better a clear refusal than an upstream error the agent cannot interpret."""
        with pytest.raises(ValueError):
            engine.trace_calls("DataCopyPad", depth=9)

    def test_a_cypher_query_reaches_the_upstream_untouched(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        """This is the one passthrough: rewriting the query would defeat its purpose."""
        cypher = "MATCH (f:Function) WHERE NOT EXISTS { (f)<-[:CALLS]-() } RETURN f.name"

        engine.query_code_graph(cypher, repo="mops")

        assert upstream.arguments_for("query_graph") == [{"query": cypher, "project": "mops"}]

    def test_an_answer_carries_the_upstream_payload_verbatim(self, root: KnowledgeBaseRoot) -> None:
        """Reshaping payloads we could not confirm would only invent structure."""
        place_repo(root, "mops")
        payload = {"languages": ["c"], "hotspots": [{"name": "main"}]}

        answer = CodeEngine(root, FakeUpstream({"get_architecture": payload})).get_architecture(
            "mops"
        )

        assert answer.payload == payload


class TestWhatWasTyped:
    """What a member types is a name they remember, not a pattern they wrote."""

    def test_a_symbol_search_takes_punctuation_literally(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        """`DataCopy(dst` is a syntax error as a pattern and a fine thing to remember."""
        engine.search_code("DataCopy(dst", repo="mops")

        (asked,) = upstream.arguments_for("search_graph")
        assert re.fullmatch(str(asked["name_pattern"]), "DataCopy(dst")

    def test_a_text_search_reaches_the_grep_as_typed(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.search_code("DataCopy(dst", mode=SearchMode.TEXT, repo="mops")

        assert upstream.arguments_for("search_code") == [
            {"query": "DataCopy(dst", "project": "mops"}
        ]

    def test_a_regex_is_only_a_regex_when_it_was_asked_for(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        engine.search_code("DataCopy.*Pad", mode=SearchMode.REGEX, repo="mops")

        assert upstream.arguments_for("search_graph") == [
            {"name_pattern": "DataCopy.*Pad", "project": "mops"}
        ]

    def test_a_broken_regex_is_refused_here_and_says_where(self, engine: CodeEngine) -> None:
        """Otherwise it comes back as whatever the upstream makes of it, which is nothing."""
        with pytest.raises(InvalidQuery, match="正则"):
            engine.search_code("DataCopy(", mode=SearchMode.REGEX, repo="mops")

    def test_an_empty_search_never_reaches_the_upstream(
        self, engine: CodeEngine, upstream: FakeUpstream
    ) -> None:
        with pytest.raises(InvalidQuery):
            engine.search_code("   ", repo="mops")
        assert upstream.calls == []


class TestNamesGoingBackUp:
    """A short name is for reading. Asking with one has to fail loudly, not quietly."""

    def test_search_results_come_back_under_both_names(self, root: KnowledgeBaseRoot) -> None:
        place_repo(root, "mops")
        found = {"results": [{"qualified_name": "_srv_kb_mops_src.copy.Run", "project": "mops"}]}

        answer = CodeEngine(root, FakeUpstream({"search_graph": found})).search_code(
            "Run", repo="mops"
        )

        found_symbols = answer.payload
        assert isinstance(found_symbols, SymbolMatches)
        (one,) = found_symbols.matches
        assert (one.canonical_qn, one.display_qn) == ("_srv_kb_mops_src.copy.Run", "mops.copy.Run")

    def test_reading_by_a_disambiguated_short_name_is_refused(self, engine: CodeEngine) -> None:
        with pytest.raises(InvalidQuery, match="canonical_qn"):
            engine.read_symbol("mops.copy.Run#a1b2c3")

    def test_tracing_from_a_disambiguated_short_name_is_refused_too(
        self, engine: CodeEngine
    ) -> None:
        with pytest.raises(InvalidQuery, match="canonical_qn"):
            engine.trace_calls("mops.copy.Run#a1b2c3")

    def test_a_traced_chain_arrives_as_nodes_and_edges(self, root: KnowledgeBaseRoot) -> None:
        place_repo(root, "mops")
        traced = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Leaf"}]]}

        answer = CodeEngine(root, FakeUpstream({"trace_path": traced})).trace_calls(
            "b.Leaf", repo="mops"
        )

        chain = answer.payload
        assert isinstance(chain, CallChain)
        assert [(one.caller, one.callee) for one in chain.edges] == [("a.Top", "b.Leaf")]
        assert chain.root == "b.Leaf"


class TestHonesty:
    """The call graph has holes, and every answer drawn from it has to say so."""

    def test_a_traced_call_chain_admits_it_may_be_missing_edges(self, engine: CodeEngine) -> None:
        assert engine.trace_calls("DataCopyPad").caveat is not None

    def test_so_do_the_architecture_overview_and_raw_graph_queries(
        self, engine: CodeEngine
    ) -> None:
        assert engine.get_architecture("mops").caveat is not None
        assert engine.query_code_graph("MATCH (f:Function) RETURN f").caveat is not None

    def test_reading_source_carries_no_such_warning(self, engine: CodeEngine) -> None:
        """A snippet is the file itself, not an inference about it."""
        assert engine.read_symbol("src.copy.DataCopyPad").caveat is None
