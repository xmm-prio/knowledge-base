"""Keeping one codebase-memory-mcp process alive for as long as the service runs.

The upstream is a child process that can crash, and the agents talking to us never reconnect
on their own. So the supervisor owns its whole life: it silences the upstream's own watcher
before starting it, replaces it when it dies, and -- the part that matters most on an upgrade
-- takes down the shared coordination daemon it leaves behind.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

from knowledge_base.code.upstream import Channel, Session, UpstreamUnavailable

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_INTERVAL = timedelta(seconds=30)
DEFAULT_RESTART_INTERVAL = timedelta(seconds=30)


class Binary(Protocol):
    """The installed executable: a server to talk to, and one-shot commands to run."""

    def spawn(self) -> Channel:
        """Start it as an MCP server. Raises UpstreamUnavailable if it will not run."""
        ...

    def run(self, *arguments: str) -> None:
        """Run one command to completion, e.g. `daemon stop`."""
        ...


class Supervisor:
    """One supervised upstream process, and the only way to reach it."""

    def __init__(
        self,
        binary: Binary,
        clock: Callable[[], float] = time.monotonic,
        health_interval: timedelta = DEFAULT_HEALTH_INTERVAL,
        restart_interval: timedelta = DEFAULT_RESTART_INTERVAL,
    ) -> None:
        self._binary = binary
        self._clock = clock
        self._health_interval = health_interval.total_seconds()
        self._restart_interval = restart_interval.total_seconds()
        self._session: Session | None = None
        self._probed = 0.0
        self._restarted_at = -math.inf

    @property
    def running(self) -> bool:
        return self._session is not None

    def start(self) -> None:
        """Prepare the upstream and bring it up. Raises if it cannot be started at all."""
        self._quiet_the_watcher()
        self._session = self._spawn()

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        """Run one upstream tool, replacing the process first if it has died."""
        session = self._live_session()
        try:
            return session.call_tool(tool, arguments)
        except UpstreamUnavailable as gone:
            logger.warning("upstream went away during %s: %s", tool, gone)
        return self._replacement().call_tool(tool, arguments)

    def check_health(self) -> bool:
        """Confirm the upstream still answers, replacing it if it does not.

        Meant for a timer that ticks faster than the probe interval; extra calls are free.
        Returns whether the upstream is usable now.
        """
        if self._clock() - self._probed < self._health_interval:
            return self.running
        self._probed = self._clock()
        session = self._live_session()
        try:
            session.ping()
        except UpstreamUnavailable as gone:
            logger.warning("upstream failed its health check: %s", gone)
        else:
            return True
        try:
            self._replacement()
        except UpstreamUnavailable:
            return False
        return True

    def stop(self) -> None:
        """Close the session and take the shared daemon down with it.

        The upstream keeps one coordination daemon per account and refuses to admit a process
        of a different version, so a daemon left running turns the next upgrade into a boot
        failure. Nothing about our own process exiting removes it.
        """
        if self._session is None:
            return
        self._session.close()
        self._session = None
        self._binary.run("daemon", "stop")

    def _live_session(self) -> Session:
        if self._session is None:
            raise UpstreamUnavailable("the upstream has not been started")
        return self._session

    def _replacement(self) -> Session:
        """Start a fresh process, unless the last replacement was too recent to be worth it.

        The interval is measured between restarts, not since the process started: one that ran
        all day and then died deserves an immediate replacement, one that dies on startup does
        not deserve a spin loop.
        """
        if self._clock() - self._restarted_at < self._restart_interval:
            raise UpstreamUnavailable("the upstream is crashing faster than it can be restarted")
        self._restarted_at = self._clock()
        self._session = self._spawn()
        return self._session

    def _spawn(self) -> Session:
        session = Session(self._binary.spawn())
        session.open()
        logger.info("upstream started")
        return session

    def _quiet_the_watcher(self) -> None:
        """Turn off the upstream's own file watcher, and make the setting take effect.

        We decide when a repository is reindexed. The upstream reads this setting once, when
        its daemon starts, so a daemon left over from an earlier run has to go first.
        """
        self._binary.run("config", "set", "watcher_enabled", "false")
        self._binary.run("daemon", "stop")
