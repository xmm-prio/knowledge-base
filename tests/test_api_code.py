"""Tests for the code domain over HTTP.

The upstream is a C binary whose payload shapes are undocumented, so every test here asserts
that the payload arrives untouched rather than asserting anything about what is in it. The
other half is failure: the binary can be missing or mid-restart, and the code page has to
degrade rather than break.
"""

from api_harness import ApiHarness

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

        await api.client.get("/api/code/search", params={"q": "DataCopy.*", "repo": "mops"})
        await api.client.get(
            "/api/code/search", params={"q": "DataCopy.*", "mode": "text", "repo": "mops"}
        )

        assert api.upstream.arguments_for("search_graph") == [
            {"name_pattern": "DataCopy.*", "project": "mops"}
        ]
        assert api.upstream.arguments_for("search_code") == [
            {"query": "DataCopy.*", "project": "mops"}
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
