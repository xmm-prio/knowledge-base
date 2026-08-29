"""Tests for the composition root: what one process contains, and what it does without."""

from __future__ import annotations

from pathlib import Path

from conftest import commits, files_in
from service_harness import BUNDLE, assembled, build_frontend
from upstream_doubles import FakeBinary

HANDSHAKE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0.1.0"},
    },
}

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}

LEARNING = """\
---
title: 对齐要求
summary: DataCopy 的搬运长度必须按 32 字节对齐
tags: [ascendc]
---

## Observations
- [pitfall] 未对齐的搬运长度会让上游静默截断 #ascendc
"""


class TestTheMcpEndpoint:
    async def test_an_agent_can_establish_a_session_through_the_composed_app(
        self, tmp_path: Path
    ) -> None:
        """Mounting an app does not run its lifespan, and an unrun session manager refuses
        every handshake. This is the test that says the host lifespan entered it."""
        async with assembled(tmp_path) as running:
            reply = await running.client.post("/mcp", json=HANDSHAKE, headers=MCP_HEADERS)

        assert reply.status_code == 200
        assert "kb" in reply.text

    async def test_the_endpoint_answers_on_the_address_agents_are_given(
        self, tmp_path: Path
    ) -> None:
        """`/mcp`, not `/mcp/`: the README, the status page and every opencode config say so."""
        async with assembled(tmp_path) as running:
            reply = await running.client.post("/mcp", json=HANDSHAKE, headers=MCP_HEADERS)

        assert reply.status_code == 200


class TestTheRestApi:
    async def test_it_is_reachable_beside_the_mcp_endpoint(self, tmp_path: Path) -> None:
        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.status_code == 200
        assert reply.json()["documents"]["ok"] is True

    async def test_the_snippet_it_hands_out_points_at_this_service(self, tmp_path: Path) -> None:
        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.json()["mcp"]["url"] == "http://kb.internal:8080/mcp"


class TestWithoutTheUpstreamBinary:
    """A workstation without a build of codebase-memory-mcp still has to run the service."""

    async def test_the_service_starts_anyway(self, tmp_path: Path) -> None:
        binary = FakeBinary()
        binary.refuses_to_spawn = True

        async with assembled(tmp_path, binary=binary) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.status_code == 200

    async def test_the_document_domain_is_unaffected(self, tmp_path: Path) -> None:
        binary = FakeBinary()
        binary.refuses_to_spawn = True

        async with assembled(tmp_path, binary=binary) as running:
            (tmp_path / "learnings").mkdir(exist_ok=True)
            (tmp_path / "learnings" / "对齐要求.md").write_text(LEARNING, encoding="utf-8")
            await running.service.documents.rebuild()
            reply = await running.client.get("/api/system/status")

        assert reply.json()["documents"] == {
            "ok": True,
            "documents": 1,
            "observations": 1,
            "tags": 1,
            "error": None,
        }

    async def test_the_code_domain_reports_itself_unavailable(self, tmp_path: Path) -> None:
        binary = FakeBinary()
        binary.refuses_to_spawn = True

        async with assembled(tmp_path, binary=binary) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.json()["code"]["ok"] is False

    async def test_asking_it_a_question_answers_with_the_reason_there_is_no_answer(
        self, tmp_path: Path
    ) -> None:
        binary = FakeBinary()
        binary.refuses_to_spawn = True

        async with assembled(tmp_path, binary=binary) as running:
            (tmp_path / "codebase" / "mops").mkdir(parents=True)
            reply = await running.client.get("/api/code/repos/mops/architecture")

        answered = reply.json()
        assert answered["ok"] is False
        assert "codebase-memory-mcp" in answered["error"]


class TestTheWebUi:
    async def test_the_built_shell_is_served_at_the_root(self, tmp_path: Path) -> None:
        frontend = build_frontend(tmp_path / "dist")

        async with assembled(tmp_path, frontend=frontend) as running:
            reply = await running.client.get("/")

        assert "<title>kb</title>" in reply.text

    async def test_built_assets_are_served_as_themselves(self, tmp_path: Path) -> None:
        frontend = build_frontend(tmp_path / "dist")

        async with assembled(tmp_path, frontend=frontend) as running:
            reply = await running.client.get("/assets/app.js")

        assert reply.content == BUNDLE

    async def test_a_path_only_the_spa_knows_gets_the_shell(self, tmp_path: Path) -> None:
        """A member reloading the browser on a client-side route must not see a 404."""
        frontend = build_frontend(tmp_path / "dist")

        async with assembled(tmp_path, frontend=frontend) as running:
            reply = await running.client.get("/documents/learnings/对齐要求.md")

        assert reply.status_code == 200
        assert "<title>kb</title>" in reply.text

    async def test_the_fallback_does_not_swallow_the_api(self, tmp_path: Path) -> None:
        frontend = build_frontend(tmp_path / "dist")

        async with assembled(tmp_path, frontend=frontend) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.headers["content-type"].startswith("application/json")

    async def test_the_fallback_does_not_swallow_the_mcp_endpoint(self, tmp_path: Path) -> None:
        frontend = build_frontend(tmp_path / "dist")

        async with assembled(tmp_path, frontend=frontend) as running:
            reply = await running.client.post("/mcp", json=HANDSHAKE, headers=MCP_HEADERS)

        assert reply.status_code == 200

    async def test_an_unbuilt_frontend_costs_the_api_nothing(self, tmp_path: Path) -> None:
        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/system/status")

        assert reply.status_code == 200


class TestStartingUp:
    async def test_the_root_layout_exists_by_the_time_anything_is_served(
        self, tmp_path: Path
    ) -> None:
        async with assembled(tmp_path):
            pass

        assert sorted(entry.name for entry in tmp_path.iterdir() if entry.is_dir()) == [
            ".git",
            ".knowledge-base",
            "codebase",
            "knowledge",
            "learnings",
        ]

    async def test_what_is_already_on_disk_is_searchable_straight_away(
        self, tmp_path: Path
    ) -> None:
        """The index is in memory and holds nothing the files do not, so booting fills it."""
        (tmp_path / "learnings").mkdir()
        (tmp_path / "learnings" / "对齐要求.md").write_text(LEARNING, encoding="utf-8")

        async with assembled(tmp_path) as running:
            reply = await running.client.get("/api/search", params={"q": "静默截断"})

        hits = reply.json()["documents"]["hits"]
        assert [found["path"] for found in hits] == ["learnings/对齐要求.md"]

    async def test_the_upstream_is_prepared_before_it_is_started(self, tmp_path: Path) -> None:
        """Its watcher setting is only read when its daemon starts, so the old one goes first."""
        binary = FakeBinary()

        async with assembled(tmp_path, binary=binary):
            pass

        assert binary.actions[:3] == [
            "config set auto_watch false",
            "daemon stop",
            "spawn",
        ]


class TestShuttingDown:
    async def test_nothing_written_is_left_out_of_history(self, tmp_path: Path) -> None:
        """The quiet period has not passed when systemd stops the service; it commits anyway."""
        async with assembled(tmp_path) as running:
            await running.client.put(
                "/api/documents/learnings/对齐要求.md",
                json={"text": LEARNING, "author": "杜宇琦"},
            )
            assert commits(tmp_path) == []

        assert files_in(tmp_path, "HEAD") == ["learnings/对齐要求.md"]

    async def test_the_shared_coordination_daemon_goes_with_it(self, tmp_path: Path) -> None:
        """It outlives our process and refuses the next version, so ADR-0007 takes it down."""
        binary = FakeBinary()

        async with assembled(tmp_path, binary=binary):
            pass

        assert binary.actions[-1] == "daemon stop"
