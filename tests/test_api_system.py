"""Tests for the system status page.

Its job is to answer three questions an operator arrives with: is anything broken, how much
is actually indexed, and what do I paste into a colleague's opencode.json.
"""

import json
from pathlib import Path

from api_harness import ApiHarness, Unreachable, running_api


class TestStatus:
    async def test_it_reports_how_much_is_indexed(self, api: ApiHarness) -> None:
        api.write(
            "learnings/ascendc/对齐要求.md",
            "---\ntitle: 对齐要求\ntags: [ascendc]\n---\n\n# 对齐要求\n\n"
            "- [pitfall] 非对齐搬运时会读到脏数据\n",
        )
        await api.documents.rebuild()

        body = (await api.client.get("/api/system/status")).json()

        assert body["documents"] == {
            "ok": True,
            "documents": 1,
            "observations": 1,
            "tags": 1,
            "error": None,
        }

    async def test_it_reports_the_code_domain_beside_it(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.place_repo("fresh")
        api.upstream.answers["list_projects"] = {"projects": [{"name": "mops"}]}

        body = (await api.client.get("/api/system/status")).json()

        assert body["code"]["repos"] == 2
        assert body["code"]["indexed"] == 1
        assert body["code"]["ok"] is True

    async def test_an_upstream_that_fails_its_health_check_says_so(self, api: ApiHarness) -> None:
        api.supervisor.healthy = False

        body = (await api.client.get("/api/system/status")).json()

        assert body["code"]["ok"] is False

    async def test_the_opencode_snippet_points_at_the_address_the_service_hands_out(
        self, api: ApiHarness
    ) -> None:
        """It is copied straight into a colleague's config, so it has to be right as it is."""
        body = (await api.client.get("/api/system/status")).json()

        configuration = json.loads(body["mcp"]["opencode_config"])

        assert body["mcp"]["url"] == "http://kb.internal:8080/mcp"
        assert configuration == {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "kb": {
                    "type": "remote",
                    "url": "http://kb.internal:8080/mcp",
                    "enabled": True,
                    "oauth": False,
                }
            },
        }

    async def test_the_snippet_does_not_change_with_the_host_the_browser_used(
        self, api: ApiHarness
    ) -> None:
        """A member on a VPN reaches the page by one name and their colleague by another. The
        snippet they copy travels, so it names the service rather than their route to it."""
        body = (
            await api.client.get("/api/system/status", headers={"Host": "somebody-elses-name"})
        ).json()

        assert body["mcp"]["url"] == "http://kb.internal:8080/mcp"

    async def test_no_address_to_hand_out_is_said_rather_than_guessed(self, tmp_path: Path) -> None:
        """A plausible address nobody can connect to costs an afternoon of confusion."""
        async with running_api(tmp_path, address=Unreachable()) as api:
            body = (await api.client.get("/api/system/status")).json()

        assert body["mcp"]["url"] == ""
        assert "没有默认路由" in body["mcp"]["error"]


class TestReindexing:
    async def test_reindexing_documents_reports_how_many_it_took_in(self, api: ApiHarness) -> None:
        api.write("knowledge/甲.md", "# 甲\n")
        api.write("knowledge/乙.md", "# 乙\n")

        body = (await api.client.post("/api/system/reindex/documents")).json()

        assert body == {"indexed": 2}

    async def test_reindexing_code_covers_every_repository(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.place_repo("ascendc-samples")

        body = (await api.client.post("/api/system/reindex/code", json={})).json()

        assert [outcome["repo"] for outcome in body["outcomes"]] == ["ascendc-samples", "mops"]
        assert all(outcome["ok"] for outcome in body["outcomes"])

    async def test_reindexing_code_can_be_narrowed_to_one_repository(self, api: ApiHarness) -> None:
        api.place_repo("mops")
        api.place_repo("ascendc-samples")

        body = (await api.client.post("/api/system/reindex/code", json={"repo": "mops"})).json()

        assert [outcome["repo"] for outcome in body["outcomes"]] == ["mops"]

    async def test_one_repository_the_upstream_chokes_on_does_not_stop_the_others(
        self, api: ApiHarness
    ) -> None:
        api.place_repo("mops")
        api.place_repo("ascendc-samples")
        api.upstream.failing.add("index_repository")

        body = (await api.client.post("/api/system/reindex/code", json={})).json()

        assert [outcome["ok"] for outcome in body["outcomes"]] == [False, False]

    async def test_reindexing_a_repository_that_is_not_there_is_a_404(
        self, api: ApiHarness
    ) -> None:
        response = await api.client.post("/api/system/reindex/code", json={"repo": "nope"})

        assert response.status_code == 404
