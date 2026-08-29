"""Tests for the upstream doubles themselves.

Everything that will be claimed about running several upstream conversations at once is
claimed against these doubles, so what they can and cannot show is worth pinning down. A
double that quietly answered a held request, or that let a killed conversation hang, would
turn a broken gateway into a passing suite.
"""

from __future__ import annotations

import threading

import pytest

from knowledge_base.code.upstream import Session, UpstreamUnavailable
from upstream_doubles import FakeBinary, Gate, echo, tool_result


def opened(channel: object) -> Session:
    session = Session(channel)  # type: ignore[arg-type]
    session.open()
    return session


def asking(
    session: Session, tool: str, arguments: dict[str, object]
) -> tuple[threading.Thread, list[object]]:
    """One tool call on its own thread, and the list its answer will land in."""
    answers: list[object] = []
    thread = threading.Thread(target=lambda: answers.append(session.call_tool(tool, arguments)))
    thread.start()
    return thread, answers


class TestHolding:
    def test_a_held_request_reaches_the_upstream_but_is_not_answered_yet(self) -> None:
        binary = FakeBinary({"search_graph": tool_result({"symbols": []})})
        session = opened(binary.spawn())
        binary.hold()

        thread, answers = asking(session, "search_graph", {})
        binary.wait_for(1)

        assert answers == []
        binary.release()
        thread.join(timeout=5)
        assert answers == [{"symbols": []}]

    def test_holding_one_conversation_leaves_the_others_answering(self) -> None:
        """The whole point of several sessions: one slow question must not stop the rest."""
        binary = FakeBinary({"search_graph": tool_result({"symbols": []})})
        held, free = opened(binary.spawn()), opened(binary.spawn())
        binary.channels[0].gate = Gate()
        binary.channels[0].gate.hold()

        thread, answers = asking(held, "search_graph", {})
        binary.channels[0].gate.wait_for(1)

        assert free.call_tool("search_graph", {}) == {"symbols": []}
        assert answers == []
        binary.channels[0].gate.release()
        thread.join(timeout=5)

    def test_it_counts_everything_in_flight_across_every_conversation(self) -> None:
        binary = FakeBinary({"search_graph": tool_result({})})
        sessions = [opened(binary.spawn()) for _ in range(3)]
        binary.hold()

        threads = [asking(one, "search_graph", {})[0] for one in sessions]
        binary.wait_for(3)

        assert binary.gate.waiting == 3
        binary.release()
        for thread in threads:
            thread.join(timeout=5)


class TestTellingConversationsApart:
    def test_each_conversation_records_only_its_own_traffic(self) -> None:
        binary = FakeBinary({"search_graph": tool_result({}), "list_projects": tool_result({})})
        first, second = opened(binary.spawn()), opened(binary.spawn())

        first.call_tool("search_graph", {})
        second.call_tool("list_projects", {})

        assert binary.channels[0].tools_called() == ["search_graph"]
        assert binary.channels[1].tools_called() == ["list_projects"]

    def test_an_answer_can_be_computed_from_the_question(self) -> None:
        """Identical answers cannot catch a reply reaching the wrong caller."""
        binary = FakeBinary({"search_graph": echo(lambda arguments: {"asked": arguments})})
        session = opened(binary.spawn())

        assert session.call_tool("search_graph", {"name_pattern": "a"}) == {
            "asked": {"name_pattern": "a"}
        }

    def test_one_shot_commands_stay_apart_from_the_conversations(self) -> None:
        binary = FakeBinary()
        binary.run("daemon", "stop")
        opened(binary.spawn())

        assert binary.actions == ["daemon stop", "spawn"]
        assert binary.channels[0].methods() == ["initialize", "notifications/initialized"]


class TestDying:
    def test_one_conversation_can_be_killed_without_touching_the_others(self) -> None:
        binary = FakeBinary({"search_graph": tool_result({})})
        doomed, survivor = opened(binary.spawn()), opened(binary.spawn())

        binary.channels[0].die()

        with pytest.raises(UpstreamUnavailable):
            doomed.call_tool("search_graph", {})
        assert survivor.call_tool("search_graph", {}) == {}
        assert binary.live == [binary.channels[1]]

    def test_a_conversation_that_dies_while_held_fails_rather_than_hanging(self) -> None:
        """A crash has to reach the caller. Waiting out the deadline is not an answer."""
        binary = FakeBinary({"search_graph": tool_result({})})
        session = opened(binary.spawn())
        binary.hold()

        failures: list[BaseException] = []

        def ask() -> None:
            try:
                session.call_tool("search_graph", {})
            except BaseException as failure:  # noqa: BLE001 - the failure is the assertion
                failures.append(failure)

        thread = threading.Thread(target=ask)
        thread.start()
        binary.wait_for(1)
        binary.channels[0].die()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert isinstance(failures[0], UpstreamUnavailable)
