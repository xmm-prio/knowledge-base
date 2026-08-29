"""Tests for several upstream conversations at once.

An MCP server answers one request at a time on one pair of pipes, so the interesting failures
here are not crashes but confusions: two callers reading each other's replies, an answer that
never arrives because somebody else took it, one crashed process taking the other three down
with it, a repository indexed twice because a dropped connection looked like a reason to try
again. Each of those is a test below.

Nothing here needs codebase-memory-mcp: the doubles hold real conversations, and the JSON-RPC
framing above them is the real one.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta

import pytest

from conftest import FakeClock
from knowledge_base.code.supervisor import Supervisor
from knowledge_base.code.upstream import UpstreamUnavailable
from upstream_doubles import FakeBinary, echo, tool_result

CONVERSATIONS = 4
CAPACITY = 20
PATIENCE = 5.0

ANSWERS = {
    "search_graph": echo(lambda arguments: {"asked": arguments}),
    "list_projects": tool_result({"projects": []}),
    "index_repository": tool_result({"status": "indexed"}),
}


def pooled(
    binary: FakeBinary,
    conversations: int = CONVERSATIONS,
    capacity: int = CAPACITY,
    queue_wait: float = PATIENCE,
) -> Supervisor:
    supervisor = Supervisor(
        binary,
        clock=FakeClock(),
        conversations=conversations,
        capacity=capacity,
        queue_wait=timedelta(seconds=queue_wait),
    )
    supervisor.start()
    return supervisor


def until(condition, timeout: float = PATIENCE) -> bool:
    """Wait for something the other threads are still bringing about."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class TestAnsweringSeveralCallersAtOnce:
    def test_it_opens_a_conversation_per_caller_up_to_its_limit(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        binary.hold()

        with ThreadPoolExecutor(max_workers=CAPACITY) as callers:
            waiting = [
                callers.submit(supervisor.call_tool, "search_graph", {"n": n})
                for n in range(CAPACITY)
            ]
            assert until(lambda: supervisor.in_flight == CAPACITY)
            binary.wait_for(CONVERSATIONS)

            assert supervisor.conversations == CONVERSATIONS
            assert binary.gate.waiting == CONVERSATIONS
            binary.release()
            answers = [one.result(timeout=PATIENCE) for one in waiting]

        assert answers == [{"asked": {"n": n}} for n in range(CAPACITY)]

    def test_no_caller_is_given_another_caller_s_answer(self) -> None:
        """The failure a shared session produces, and the reason there are several."""
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)

        with ThreadPoolExecutor(max_workers=CAPACITY) as callers:
            waiting = [
                callers.submit(supervisor.call_tool, "search_graph", {"n": n}) for n in range(60)
            ]
            answers = [one.result(timeout=PATIENCE) for one in waiting]

        assert answers == [{"asked": {"n": n}} for n in range(60)]

    def test_one_slow_question_does_not_hold_up_the_others(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        supervisor.call_tool("search_graph", {"n": 0})
        slow = binary.channels[0]
        slow.delay = 0.4

        with ThreadPoolExecutor(max_workers=2) as callers:
            started = time.monotonic()
            held = callers.submit(supervisor.call_tool, "search_graph", {"n": 1})
            assert until(lambda: binary.gate.waiting == 0 and slow.delay > 0)
            quick = callers.submit(supervisor.call_tool, "search_graph", {"n": 2})
            quick.result(timeout=PATIENCE)
            elapsed = time.monotonic() - started
            held.result(timeout=PATIENCE)

        assert elapsed < 0.4

    def test_a_conversation_is_reused_rather_than_reopened(self) -> None:
        """Long-lived is the point: the upstream costs seconds of migrations to start."""
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)

        for n in range(5):
            supervisor.call_tool("search_graph", {"n": n})

        assert len(binary.channels) == 1


class TestWhenOneProcessDies:
    def test_a_crash_on_one_conversation_leaves_the_others_answering(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        binary.hold()

        with ThreadPoolExecutor(max_workers=CONVERSATIONS) as callers:
            waiting = [
                callers.submit(supervisor.call_tool, "search_graph", {"n": n})
                for n in range(CONVERSATIONS)
            ]
            binary.wait_for(CONVERSATIONS)
            doomed = binary.channels[0]
            survivors = list(binary.channels[1:])
            doomed.die()
            binary.release()
            answers = [one.result(timeout=PATIENCE) for one in waiting]

        assert sorted(str(one) for one in answers) == sorted(
            str({"asked": {"n": n}}) for n in range(CONVERSATIONS)
        )
        assert all(not one.closed for one in survivors)

    def test_a_question_cut_off_by_a_crash_is_asked_again(self) -> None:
        """opencode never reconnects, so a crash must not surface as a broken connection."""
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        supervisor.call_tool("list_projects", {})
        binary.channels[0].die()

        assert supervisor.call_tool("list_projects", {}) == {"projects": []}
        assert len(binary.channels) == 2

    def test_a_change_cut_off_by_a_crash_is_not_made_twice(self) -> None:
        """A dropped connection says nothing about whether the call ran. Indexing a repository
        a second time is not free, and reporting success for a half-finished one is worse."""
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        supervisor.call_tool("list_projects", {})
        binary.channels[0].die()

        with pytest.raises(UpstreamUnavailable, match="not sent again"):
            supervisor.call_tool("index_repository", {"repo_path": "/kb/codebase/mops"})

        assert [one.tools_called() for one in binary.channels] == [["list_projects"]]

    def test_a_crash_costs_only_the_conversation_it_happened_on(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        binary.hold()

        with ThreadPoolExecutor(max_workers=CONVERSATIONS) as callers:
            waiting = [
                callers.submit(supervisor.call_tool, "search_graph", {"n": n})
                for n in range(CONVERSATIONS)
            ]
            binary.wait_for(CONVERSATIONS)
            binary.channels[0].die()
            binary.release()
            for one in waiting:
                one.result(timeout=PATIENCE)

        assert len(binary.channels) == CONVERSATIONS + 1


class TestWhenEveryConversationIsBusy:
    def test_a_caller_beyond_the_conversations_waits_for_its_turn(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary, conversations=1)
        binary.hold()

        with ThreadPoolExecutor(max_workers=2) as callers:
            first = callers.submit(supervisor.call_tool, "search_graph", {"n": 0})
            binary.wait_for(1)
            second = callers.submit(supervisor.call_tool, "search_graph", {"n": 1})
            assert until(lambda: supervisor.in_flight == 2)
            binary.release()

            assert first.result(timeout=PATIENCE) == {"asked": {"n": 0}}
            assert second.result(timeout=PATIENCE) == {"asked": {"n": 1}}
        assert len(binary.channels) == 1

    def test_a_caller_beyond_the_capacity_is_told_rather_than_left_waiting(self) -> None:
        """The queue is bounded on purpose: a pile of threads waiting on a wedged upstream is
        an outage that reports itself as slowness."""
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary, conversations=1, capacity=1, queue_wait=0.05)
        binary.hold()
        started = threading.Event()

        def first() -> object:
            started.set()
            return supervisor.call_tool("search_graph", {"n": 0})

        with ThreadPoolExecutor(max_workers=2) as callers:
            held = callers.submit(first)
            started.wait(PATIENCE)
            binary.wait_for(1)

            with pytest.raises(UpstreamUnavailable, match="too many"):
                supervisor.call_tool("search_graph", {"n": 1})

            binary.release()
            held.result(timeout=PATIENCE)


class TestHealth:
    def test_a_probe_does_not_interrupt_a_conversation_that_is_mid_answer(self) -> None:
        """A ping down a busy pipe would be read as that exchange's reply."""
        binary = FakeBinary(ANSWERS)
        clock = FakeClock()
        supervisor = Supervisor(binary, clock=clock, conversations=1, capacity=CAPACITY)
        supervisor.start()
        binary.hold()

        with ThreadPoolExecutor(max_workers=1) as callers:
            answering: Future[object] = callers.submit(
                supervisor.call_tool, "search_graph", {"n": 0}
            )
            binary.wait_for(1)
            clock.advance(60)

            assert supervisor.check_health() is True
            assert binary.channels[0].tools_called() == ["search_graph"]
            binary.release()
            assert answering.result(timeout=PATIENCE) == {"asked": {"n": 0}}

    def test_a_probe_does_not_open_a_conversation_nobody_asked_for(self) -> None:
        binary = FakeBinary(ANSWERS)
        clock = FakeClock()
        supervisor = Supervisor(binary, clock=clock, conversations=CONVERSATIONS)
        supervisor.start()
        binary.hold()

        with ThreadPoolExecutor(max_workers=1) as callers:
            answering = callers.submit(supervisor.call_tool, "search_graph", {"n": 0})
            binary.wait_for(1)
            clock.advance(60)
            supervisor.check_health()
            binary.release()
            answering.result(timeout=PATIENCE)

        assert supervisor.conversations == 1


class TestStopping:
    def test_it_closes_every_conversation_it_opened(self) -> None:
        binary = FakeBinary(ANSWERS)
        supervisor = pooled(binary)
        binary.hold()

        with ThreadPoolExecutor(max_workers=CONVERSATIONS) as callers:
            waiting = [
                callers.submit(supervisor.call_tool, "search_graph", {"n": n})
                for n in range(CONVERSATIONS)
            ]
            binary.wait_for(CONVERSATIONS)
            binary.release()
            for one in waiting:
                one.result(timeout=PATIENCE)

        supervisor.stop()

        assert binary.live == []
        assert binary.actions[-1] == "daemon stop"
