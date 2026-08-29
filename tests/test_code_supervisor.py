"""Tests for the lifecycle of the supervised upstream binary.

The clock and the binary are both injected, so a crash-loop guard measured in minutes costs a
test nothing, and no test needs codebase-memory-mcp installed.
"""

from datetime import timedelta

import pytest

from conftest import FakeClock
from knowledge_base.code.supervisor import Supervisor
from knowledge_base.code.upstream import UpstreamRefused, UpstreamUnavailable
from upstream_doubles import FakeBinary, tool_result

HEALTH = timedelta(seconds=30)
RESTART = timedelta(seconds=60)


def supervised(binary: FakeBinary, clock: FakeClock | None = None) -> Supervisor:
    supervisor = Supervisor(
        binary,
        clock=clock or FakeClock(),
        health_interval=HEALTH,
        restart_interval=RESTART,
    )
    supervisor.start()
    return supervisor


class TestStarting:
    def test_it_silences_the_upstream_watcher_before_the_process_exists(self) -> None:
        """We index on our own schedule; its watcher would re-index behind our back. The
        setting is only read when its daemon starts, so a stale daemon has to go first."""
        binary = FakeBinary()

        supervised(binary)

        assert binary.actions == [
            "config set auto_watch false",
            "daemon stop",
            "spawn",
        ]

    def test_it_opens_an_mcp_session_on_the_process_it_started(self) -> None:
        binary = FakeBinary()

        supervised(binary)

        assert binary.channel.methods() == ["initialize", "notifications/initialized"]

    def test_a_binary_that_will_not_start_is_reported_at_once(self) -> None:
        """Better a failure at boot than every tool call failing mysteriously later."""
        binary = FakeBinary()
        binary.refuses_to_spawn = True

        with pytest.raises(UpstreamUnavailable):
            supervised(binary)


class TestAnswering:
    def test_it_forwards_tool_calls_to_the_running_process(self) -> None:
        binary = FakeBinary({"list_projects": tool_result({"projects": []})})

        assert supervised(binary).call_tool("list_projects", {}) == {"projects": []}

    def test_a_call_before_it_started_is_refused_rather_than_starting_one_implicitly(self) -> None:
        supervisor = Supervisor(FakeBinary(), clock=FakeClock())

        with pytest.raises(UpstreamUnavailable):
            supervisor.call_tool("list_projects", {})

    def test_a_crash_mid_call_is_answered_by_a_fresh_process(self) -> None:
        """opencode never reconnects, so a crash must not surface as a broken connection."""
        binary = FakeBinary({"list_projects": tool_result({"projects": []})})
        supervisor = supervised(binary)
        binary.channel.die()

        assert supervisor.call_tool("list_projects", {}) == {"projects": []}
        assert len(binary.channels) == 2

    def test_a_tool_the_upstream_refuses_does_not_cost_a_restart(self) -> None:
        """An unsupported Cypher clause is the caller's problem, not the process's."""
        refusal = {
            "result": {"content": [{"type": "text", "text": "unsupported"}], "isError": True}
        }
        binary = FakeBinary({"query_graph": refusal})
        supervisor = supervised(binary)

        with pytest.raises(UpstreamRefused):
            supervisor.call_tool("query_graph", {})

        assert len(binary.channels) == 1


class TestHealth:
    def test_it_probes_no_more_often_than_its_interval(self) -> None:
        """The check runs on a timer that ticks faster than we want to bother the upstream."""
        clock = FakeClock()
        binary = FakeBinary()
        supervisor = supervised(binary, clock)

        clock.advance(HEALTH.total_seconds())
        supervisor.check_health()
        supervisor.check_health()

        assert binary.channel.methods().count("tools/list") == 1

    def test_a_process_that_died_quietly_is_replaced_at_the_next_probe(self) -> None:
        """Nothing may have called a tool for an hour; the crash still has to be noticed."""
        clock = FakeClock()
        binary = FakeBinary()
        supervisor = supervised(binary, clock)
        binary.channel.die()

        clock.advance(HEALTH.total_seconds())

        assert supervisor.check_health() is True
        assert len(binary.channels) == 2

    def test_a_process_that_keeps_dying_is_not_respawned_in_a_tight_loop(self) -> None:
        """A binary crashing on startup would otherwise burn a core forever."""
        clock = FakeClock()
        binary = FakeBinary()
        supervisor = supervised(binary, clock)

        binary.channel.die()
        clock.advance(HEALTH.total_seconds())
        supervisor.check_health()

        binary.channel.die()
        clock.advance(HEALTH.total_seconds())

        assert supervisor.check_health() is False
        assert len(binary.channels) == 2

    def test_it_tries_again_once_the_restart_interval_has_passed(self) -> None:
        clock = FakeClock()
        binary = FakeBinary()
        supervisor = supervised(binary, clock)

        binary.channel.die()
        clock.advance(HEALTH.total_seconds())
        supervisor.check_health()

        binary.channel.die()
        clock.advance(RESTART.total_seconds())

        assert supervisor.check_health() is True
        assert len(binary.channels) == 3


class TestStopping:
    def test_it_stops_the_shared_daemon_the_upstream_leaves_behind(self) -> None:
        """The per-account daemon cannot be disabled and refuses any process of another
        version, so leaving one running turns the next upgrade into a boot failure."""
        binary = FakeBinary()
        supervisor = supervised(binary)
        binary.actions.clear()

        supervisor.stop()

        assert binary.actions == ["daemon stop"]
        assert binary.channel.closed

    def test_stopping_twice_stops_the_daemon_once(self) -> None:
        binary = FakeBinary()
        supervisor = supervised(binary)
        binary.actions.clear()

        supervisor.stop()
        supervisor.stop()

        assert binary.actions == ["daemon stop"]

    def test_stopping_something_that_never_started_is_not_an_error(self) -> None:
        """Shutdown runs after a failed boot too."""
        binary = FakeBinary()

        Supervisor(binary, clock=FakeClock()).stop()

        assert binary.actions == []
