"""Tests for the conversation with the upstream binary.

The binary is an MCP server speaking newline-delimited JSON-RPC on its standard streams. The
channel is the seam: these tests drive a fake one, so nothing here needs the binary installed.
"""

import pytest

from knowledge_base.code.upstream import (
    Session,
    UpstreamFailed,
    UpstreamRefused,
    UpstreamUnavailable,
)
from upstream_doubles import FakeChannel, tool_result


def opened(channel: FakeChannel) -> Session:
    session = Session(channel)
    session.open()
    channel.sent.clear()
    return session


class TestOpening:
    def test_it_performs_the_handshake_before_anything_else(self) -> None:
        channel = FakeChannel()

        Session(channel).open()

        assert channel.methods() == ["initialize", "notifications/initialized"]

    def test_it_introduces_itself_as_this_service(self) -> None:
        """The upstream logs the client name, which is how an operator tells sessions apart."""
        channel = FakeChannel()

        Session(channel).open()

        params = channel.sent[0]["params"]
        assert params["clientInfo"]["name"] == "knowledge-base"  # type: ignore[index]
        assert params["protocolVersion"]  # type: ignore[index]


class TestCallingTools:
    def test_it_names_the_tool_and_its_arguments(self) -> None:
        channel = FakeChannel({"list_projects": tool_result([])})
        session = opened(channel)

        session.call_tool("list_projects", {})

        assert channel.sent[0]["method"] == "tools/call"
        assert channel.sent[0]["params"] == {"name": "list_projects", "arguments": {}}

    def test_it_returns_the_json_the_upstream_wrote_into_its_text_content(self) -> None:
        payload = {"projects": [{"name": "mops"}]}
        session = opened(FakeChannel({"list_projects": tool_result(payload)}))

        assert session.call_tool("list_projects", {}) == payload

    def test_structured_content_wins_when_the_upstream_provides_it(self) -> None:
        """Newer MCP servers answer twice over; the structured half needs no reparsing."""
        result = {
            "result": {
                "content": [{"type": "text", "text": "not json at all"}],
                "structuredContent": {"projects": []},
            }
        }
        session = opened(FakeChannel({"list_projects": result}))

        assert session.call_tool("list_projects", {}) == {"projects": []}

    def test_prose_the_upstream_did_not_encode_as_json_comes_back_as_text(self) -> None:
        result = {"result": {"content": [{"type": "text", "text": "indexed 42 files"}]}}
        session = opened(FakeChannel({"index_repository": result}))

        assert session.call_tool("index_repository", {}) == "indexed 42 files"

    def test_a_tool_that_reports_failure_is_raised_not_returned(self) -> None:
        result = {
            "result": {"content": [{"type": "text", "text": "unsupported MERGE"}], "isError": True}
        }
        session = opened(FakeChannel({"query_graph": result}))

        with pytest.raises(UpstreamRefused, match="unsupported MERGE"):
            session.call_tool("query_graph", {})

    def test_a_protocol_level_error_is_raised_too(self) -> None:
        result = {"error": {"code": -32601, "message": "Method not found"}}
        session = opened(FakeChannel({"nonesuch": result}))

        with pytest.raises(UpstreamFailed, match="Method not found"):
            session.call_tool("nonesuch", {})

    def test_notifications_arriving_first_do_not_get_mistaken_for_the_answer(self) -> None:
        """The upstream reports indexing progress on the same stream as its replies."""
        channel = FakeChannel({"index_repository": tool_result({"status": "indexed"})})
        session = opened(channel)
        channel.noise = [
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}}
        ]

        assert session.call_tool("index_repository", {}) == {"status": "indexed"}

    def test_a_channel_that_went_away_is_reported_as_unavailable(self) -> None:
        """The supervisor restarts on this, so it must be distinguishable from a refusal."""
        channel = FakeChannel()
        session = opened(channel)
        channel.die()

        with pytest.raises(UpstreamUnavailable):
            session.call_tool("list_projects", {})

    def test_closing_the_session_closes_the_channel(self) -> None:
        channel = FakeChannel()
        session = opened(channel)

        session.close()

        assert channel.closed
