"""Tests for the code domain over HTTP.

The upstream is a C binary whose payload shapes are undocumented, so a payload this service
cannot read into arrives untouched rather than reshaped on a guess. Where it can -- symbol
matches, call chains -- the answer is this service's own, and the tests say so. The other
half is failure: the binary can be missing or mid-restart, and the code page has to degrade
rather than break, while still telling a member whose typo it was.
"""

from api_harness import ApiHarness
from knowledge_base.code.upstream import UpstreamUnavailable

ARCHITECTURE = {"languages": ["c"], "hotspots": [{"name": "main"}]}


class TestRepos:
    async def test_it_lists_what_an_operator_put_under_codebase(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.place_repo("ascendc-samples")

        body = (await api.client.get("/api/code/repos")).json()

        assert [repo["name"] for repo in body["repos"]] == ["ascendc-samples", "mops"]
        assert body["repos"][0]["path"] == "codebase/ascendc-samples"

    async def test_being_on_disk_and_being_indexed_are_reported_apart(
        self, api: ApiHarness
    ) -> None:
        api.place_repo("mops")
        api.place_repo("fresh")
        api.upstream.answers["list_projects"] = {"projects": [{"name": "mops"}]}

        body = (await api.client.get("/api/code/repos")).json()

        assert {repo["name"]: repo["indexed"] for repo in body["repos"]} == {
            "mops": True,
            "fresh": False,
        }

    async def test_rebuilding_one_repository_reports_what_the_upstream_said(
        self, api: ApiHarness
    ) -> None:
        api.place_repo("mops")
        api.upstream.answers["index_repository"] = {"status": "degraded", "nodes": 12}

        body = (await api.client.post("/api/code/repos/mops/index")).json()

        assert body == {"repo": "mops", "ok": True, "payload": {"status": "degraded", "nodes": 12}}


class TestAsking:
    async def test_the_architecture_overview_crosses_verbatim(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.upstream.answers["get_architecture"] = ARCHITECTURE

        body = (await api.client.get("/api/code/repos/mops/architecture")).json()

        assert body["ok"] is True
        assert body["payload"] == ARCHITECTURE

    async def test_an_answer_off_the_call_graph_admits_it_may_be_missing_edges(
        self, api: ApiHarness
    ) -> None:
        """Only 12 languages get type resolution; the rest fall back to text matching."""
        api.place_repo("mops")

        body = (await api.client.get("/api/code/calls", params={"symbol": "DataCopyPad"})).json()

        assert body["caveat"]

    async def test_reading_a_symbol_carries_no_such_warning(self, api: ApiHarness) -> None:
        body = (await api.client.get("/api/code/symbol", params={"name": "src.a.B"})).json()

        assert body["caveat"] is None

    async def test_symbol_search_and_text_search_are_different_questions(
        self, api: ApiHarness
    ) -> None:
        api.place_repo("mops")

        await api.client.get("/api/code/search", params={"q": "DataCopyPad", "repo": "mops"})
        await api.client.get(
            "/api/code/search", params={"q": "DataCopyPad", "mode": "text", "repo": "mops"}
        )

        assert api.upstream.arguments_for("search_graph") == [
            {"name_pattern": "DataCopyPad", "project": "mops"}
        ]
        assert api.upstream.arguments_for("search_code") == [
            {"query": "DataCopyPad", "project": "mops"}
        ]

    async def test_tracing_takes_a_direction_and_a_depth(self, api: ApiHarness) -> None:
        await api.client.get(
            "/api/code/calls",
            params={"symbol": "DataCopyPad", "direction": "outbound", "depth": 5},
        )

        assert api.upstream.arguments_for("trace_path") == [
            {"function_name": "DataCopyPad", "direction": "outbound", "depth": 5}
        ]

    async def test_a_depth_the_upstream_cannot_honour_is_refused(self, api: ApiHarness) -> None:
        response = await api.client.get(
            "/api/code/calls", params={"symbol": "DataCopyPad", "depth": 9}
        )

        assert response.status_code == 422

    async def test_a_cypher_query_reaches_the_upstream_untouched(self, api: ApiHarness) -> None:
        cypher = "MATCH (f:Function) WHERE NOT EXISTS { (f)<-[:CALLS]-() } RETURN f.name"

        await api.client.post("/api/code/query", json={"cypher": cypher})

        assert api.upstream.arguments_for("query_graph") == [{"query": cypher}]


class TestWhenTheUpstreamCannotAnswer:
    async def test_a_failure_is_reported_inside_the_answer_not_as_a_status(
        self, api: ApiHarness
    ) -> None:
        """The code page sits beside documents; a wedged binary must not blank the page."""
        api.place_repo("mops")
        api.upstream.failing.add("get_architecture")

        response = await api.client.get("/api/code/repos/mops/architecture")

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["error"]

    async def test_asking_about_a_repository_that_is_not_there_is_a_404(
        self, api: ApiHarness
    ) -> None:
        """A wrong request and a flaky upstream are different things."""
        response = await api.client.get("/api/code/repos/nope/architecture")

        assert response.status_code == 404

    async def test_a_missing_binary_and_a_mistyped_pattern_are_told_apart(
        self, api: ApiHarness
    ) -> None:
        """Shown as one thing, they send the member to an operator over their own typo."""
        api.place_repo("mops")
        api.upstream.raising["search_graph"] = UpstreamUnavailable("the binary is gone")

        gone = (await api.client.get("/api/code/search", params={"q": "Run"})).json()
        typo = (
            await api.client.get("/api/code/search", params={"q": "Run(", "mode": "regex"})
        ).json()

        assert gone["kind"] == "unavailable"
        assert typo["kind"] == "bad_request"

    async def test_a_failure_can_be_quoted_to_whoever_keeps_the_logs(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.upstream.raising["search_graph"] = UpstreamUnavailable("the binary is gone")

        body = (await api.client.get("/api/code/search", params={"q": "Run"})).json()

        assert body["diagnostic"]

    async def test_a_bad_pattern_never_reaches_the_upstream(self, api: ApiHarness) -> None:
        await api.client.get("/api/code/search", params={"q": "Run(", "mode": "regex"})

        assert api.upstream.calls == []


class TestWhatTheAnswerLooksLike:
    async def test_a_symbol_search_arrives_named_twice(self, api: ApiHarness) -> None:
        """One name to read on screen, one to hand back when the row is clicked."""
        api.place_repo("mops")
        api.upstream.answers["search_graph"] = {
            "results": [{"qualified_name": "_srv_kb_mops_src.copy.Run", "project": "mops"}]
        }

        body = (await api.client.get("/api/code/search", params={"q": "Run"})).json()

        (one,) = body["payload"]["matches"]
        assert one["canonical_qn"] == "_srv_kb_mops_src.copy.Run"
        assert one["display_qn"] == "mops.copy.Run"

    async def test_a_traced_chain_arrives_as_nodes_and_edges(self, api: ApiHarness) -> None:
        """A generic JSON tree cannot say who calls whom, which is the whole question."""
        api.upstream.answers["trace_path"] = {"paths": [[{"qn": "a.Top"}, {"qn": "b.Leaf"}]]}

        body = (await api.client.get("/api/code/calls", params={"symbol": "b.Leaf"})).json()

        assert body["payload"]["edges"] == [{"caller": "a.Top", "callee": "b.Leaf"}]

    async def test_what_could_not_be_resolved_is_counted_beside_the_answer(
        self, api: ApiHarness
    ) -> None:
        api.upstream.answers["trace_path"] = {
            "edges": [{"caller": "a.Top", "callee": "b.Leaf"}, {"caller": "a.Top"}]
        }

        body = (await api.client.get("/api/code/calls", params={"symbol": "b.Leaf"})).json()

        assert body["payload"]["unresolved"] == 1
